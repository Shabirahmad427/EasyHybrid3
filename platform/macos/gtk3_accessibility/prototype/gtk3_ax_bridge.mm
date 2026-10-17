#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <pygobject.h>
#include <gtk/gtk.h>
#include <atk/atk.h>
#import <AppKit/AppKit.h>
#import <objc/runtime.h>

/* GDK's Cocoa access header omits G_BEGIN_DECLS; declare its exported C symbols explicitly. */
extern "C" {
NSWindow *gdk_quartz_window_get_nswindow(GdkWindow *window);
NSView *gdk_quartz_window_get_nsview(GdkWindow *window);
}

static char kChildrenKey;
static NSMutableDictionary<NSString *, NSValue *> *originalChildrenImplementations;

typedef struct {
  GtkWidget *widget;             /* weak pointer; invalidated on GTK destruction */
  AtkObject *accessible;         /* strong GObject reference */
} PressRequest;

@interface EH3GtkButtonElement : NSAccessibilityElement {
  GtkWidget *_widget;
  AtkObject *_accessible;
  __weak NSView *_parentView;
  NSString *_label;
  NSRect _screenFrame;
  BOOL _enabled;
  BOOL _visible;
}
- (instancetype)initWithWidget:(GtkWidget *)widget accessible:(AtkObject *)accessible parent:(NSView *)parent;
- (void)refreshFromGtk;
@end

@implementation EH3GtkButtonElement
- (instancetype)initWithWidget:(GtkWidget *)widget accessible:(AtkObject *)accessible parent:(NSView *)parent {
  self = [super init];
  if (!self) return nil;
  _widget = widget;
  g_object_add_weak_pointer(G_OBJECT(widget), (gpointer *)&_widget);
  _accessible = g_object_ref(accessible);
  _parentView = parent;
  [self refreshFromGtk];
  return self;
}

- (void)refreshFromGtk {
  if (!_widget) {
    _enabled = NO;
    _visible = NO;
    return;
  }
  const gchar *name = atk_object_get_name(_accessible);
  _label = name ? [NSString stringWithUTF8String:name] : @"";
  _enabled = gtk_widget_is_sensitive(_widget);
  GtkWidget *toplevel = gtk_widget_get_toplevel(_widget);
  _visible = gtk_widget_get_visible(_widget) && GTK_IS_WIDGET(toplevel) && gtk_widget_get_visible(toplevel);
  AtkRectangle extents = {0};
  if (ATK_IS_COMPONENT(_accessible)) {
    atk_component_get_extents(ATK_COMPONENT(_accessible), &extents.x, &extents.y,
                              &extents.width, &extents.height, ATK_XY_SCREEN);
    NSScreen *screen = _parentView.window.screen ?: NSScreen.mainScreen;
    CGFloat screenTop = NSMaxY(screen.frame);
    _screenFrame = NSMakeRect(extents.x, screenTop - (extents.y + extents.height),
                              extents.width, extents.height);
  } else {
    _screenFrame = _parentView.window.frame;
  }
  NSAccessibilityPostNotification(self, NSAccessibilityValueChangedNotification);
}

- (void)dealloc {
  if (_widget) g_object_remove_weak_pointer(G_OBJECT(_widget), (gpointer *)&_widget);
  if (_accessible) g_object_unref(_accessible);
}

- (NSString *)accessibilityRole { return NSAccessibilityButtonRole; }
- (NSString *)accessibilityTitle { return _label; }
- (NSString *)accessibilityLabel { return _label; }
- (NSRect)accessibilityFrame { return _screenFrame; }
- (id)accessibilityParent { return _parentView; }
- (BOOL)isAccessibilityElement { return YES; }
- (BOOL)isAccessibilityEnabled { return _enabled && _visible && _widget != NULL; }
- (BOOL)isAccessibilityHidden { return !_visible; }
- (NSArray<NSString *> *)accessibilityActionNames { return @[ NSAccessibilityPressAction ]; }
- (NSString *)accessibilityActionDescription:(NSString *)action { return [action isEqualToString:NSAccessibilityPressAction] ? @"Press" : @""; }

- (BOOL)accessibilityPerformPress {
  if (!_widget || !_enabled || !_visible || !ATK_IS_ACTION(_accessible)) return NO;
  PressRequest *request = g_new0(PressRequest, 1);
  request->widget = _widget;
  g_object_add_weak_pointer(G_OBJECT(request->widget), (gpointer *)&request->widget);
  request->accessible = g_object_ref(_accessible);
  g_idle_add_full(G_PRIORITY_DEFAULT, [](gpointer data) -> gboolean {
    PressRequest *press = static_cast<PressRequest *>(data);
    if (press->widget && GTK_IS_WIDGET(press->widget) && ATK_IS_ACTION(press->accessible))
      atk_action_do_action(ATK_ACTION(press->accessible), 0);
    return G_SOURCE_REMOVE;
  }, request, [](gpointer data) {
    PressRequest *press = static_cast<PressRequest *>(data);
    if (press->widget) g_object_remove_weak_pointer(G_OBJECT(press->widget), (gpointer *)&press->widget);
    g_object_unref(press->accessible);
    g_free(press);
  });
  return YES;
}

@end

static NSArray *EH3AccessibilityChildren(id self, SEL selector) {
  NSString *key = NSStringFromClass([self class]);
  IMP original = reinterpret_cast<IMP>(originalChildrenImplementations[key].pointerValue);
  NSArray *base = original ? ((id (*)(id, SEL))original)(self, selector) : @[];
  NSArray *extra = objc_getAssociatedObject(self, &kChildrenKey);
  if (!extra.count) return base ?: @[];
  NSMutableArray *children = base ? [base mutableCopy] : [NSMutableArray array];
  for (id child in extra) if (![children containsObject:child]) [children addObject:child];
  return children;
}

static void EH3WidgetNotify(GObject *object, GParamSpec *property, gpointer data) {
  (void)object;
  (void)property;
  EH3GtkButtonElement *element = (__bridge EH3GtkButtonElement *)data;
  [element refreshFromGtk];
}

static void EH3ReleaseElement(gpointer data, GClosure *closure) {
  (void)closure;
  CFBridgingRelease(data);
}

static BOOL InstallChildrenHook(NSView *view) {
  Class cls = object_getClass(view);
  NSString *key = NSStringFromClass(cls);
  if (originalChildrenImplementations[key]) return YES;
  SEL selector = @selector(accessibilityChildren);
  Method inherited = class_getInstanceMethod(cls, selector);
  IMP original = inherited ? method_getImplementation(inherited) : NULL;
  const char *types = inherited ? method_getTypeEncoding(inherited) : "@@:";
  originalChildrenImplementations[key] = [NSValue valueWithPointer:reinterpret_cast<void *>(original)];
  if (!class_addMethod(cls, selector, (IMP)EH3AccessibilityChildren, types)) {
    Method own = class_getInstanceMethod(cls, selector);
    method_setImplementation(own, (IMP)EH3AccessibilityChildren);
  }
  return YES;
}

static PyObject *bridge_install_button(PyObject *self, PyObject *arg) {
  (void)self;
  GObject *object = pygobject_get(arg);
  if (!object || !GTK_IS_BUTTON(object)) {
    PyErr_SetString(PyExc_TypeError, "expected a Gtk.Button");
    return NULL;
  }
  GtkWidget *button = GTK_WIDGET(object);
  GtkWidget *toplevel = gtk_widget_get_toplevel(button);
  if (!GTK_IS_WINDOW(toplevel) || !gtk_widget_get_realized(toplevel)) {
    PyErr_SetString(PyExc_RuntimeError, "button must belong to a realized Gtk.Window");
    return NULL;
  }
  GdkWindow *gdkWindow = gtk_widget_get_window(toplevel);
  NSWindow *nativeWindow = gdk_quartz_window_get_nswindow(gdkWindow);
  NSView *nativeView = gdk_quartz_window_get_nsview(gdkWindow);
  if (!nativeWindow || !nativeView) {
    PyErr_SetString(PyExc_RuntimeError, "GDK Quartz did not provide its NSWindow and NSView");
    return NULL;
  }
  AtkObject *accessible = gtk_widget_get_accessible(button);
  if (!ATK_IS_ACTION(accessible) || !ATK_IS_COMPONENT(accessible)) {
    PyErr_SetString(PyExc_RuntimeError, "Gtk.Button ATK object lacks AtkAction or AtkComponent");
    return NULL;
  }

  @autoreleasepool {
    if (!originalChildrenImplementations) originalChildrenImplementations = [NSMutableDictionary dictionary];
    InstallChildrenHook(nativeView);
    EH3GtkButtonElement *element = [[EH3GtkButtonElement alloc] initWithWidget:button accessible:accessible parent:nativeView];
    NSMutableArray *children = objc_getAssociatedObject(nativeView, &kChildrenKey);
    if (!children) children = [NSMutableArray array];
    [children addObject:element];
    objc_setAssociatedObject(nativeView, &kChildrenKey, children, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
    g_signal_connect_data(button, "notify", G_CALLBACK(EH3WidgetNotify),
                          (gpointer)CFBridgingRetain(element), EH3ReleaseElement, G_CONNECT_DEFAULT);
    g_signal_connect_data(toplevel, "notify::visible", G_CALLBACK(EH3WidgetNotify),
                          (gpointer)CFBridgingRetain(element), EH3ReleaseElement, G_CONNECT_DEFAULT);
    fprintf(stdout, "NATIVE_BRIDGE window=%p window-class=%s view=%p view-class=%s role=%s label=%s frame={{%.1f,%.1f},{%.1f,%.1f}}\n",
            nativeWindow, class_getName([nativeWindow class]), nativeView, class_getName([nativeView class]),
            [element.accessibilityRole UTF8String], [element.accessibilityLabel UTF8String],
            element.accessibilityFrame.origin.x, element.accessibilityFrame.origin.y,
            element.accessibilityFrame.size.width, element.accessibilityFrame.size.height);
    [nativeWindow makeKeyAndOrderFront:nil];
    NSAccessibilityPostNotification(nativeView, NSAccessibilityLayoutChangedNotification);
  }
  Py_RETURN_NONE;
}

static PyObject *bridge_finish_launching(PyObject *self, PyObject *Py_UNUSED(ignored)) {
  (void)self;
  @autoreleasepool {
    [NSApp finishLaunching];
    fprintf(stdout, "APPKIT finishLaunching called running=%s active=%s window-count=%lu\n",
            NSApp.isRunning ? "yes" : "no", NSApp.isActive ? "yes" : "no",
            (unsigned long)NSApp.windows.count);
  }
  Py_RETURN_NONE;
}

static PyMethodDef methods[] = {
  {"install_button", (PyCFunction)bridge_install_button, METH_O, "Expose a Gtk.Button ATK object through the real GDK Quartz NSView."},
  {"finish_launching", (PyCFunction)bridge_finish_launching, METH_NOARGS, "Run the isolated GDK Quartz finishLaunching experiment."},
  {NULL, NULL, 0, NULL}
};

static struct PyModuleDef module = { PyModuleDef_HEAD_INIT, "gtk3_ax_bridge", NULL, -1, methods };

PyMODINIT_FUNC PyInit_gtk3_ax_bridge(void) {
  PyObject *gobjectModule = pygobject_init(-1, -1, -1);
  if (!gobjectModule) return NULL;
  Py_DECREF(gobjectModule);
  return PyModule_Create(&module);
}
