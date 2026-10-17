#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <pygobject.h>
#include <gtk/gtk.h>
#include <atk/atk.h>
#import <AppKit/AppKit.h>
#import <objc/runtime.h>
#include <pthread.h>
#include <cstdlib>
#include <condition_variable>
#include <chrono>
#include <cstring>
#include <mutex>
#include <thread>

extern "C" {
NSWindow *gdk_quartz_window_get_nswindow(GdkWindow *window);
NSView *gdk_quartz_window_get_nsview(GdkWindow *window);
}

static char kChildrenKey;
static const char *kNodeDataKey = "easyhybrid3-nsaccessibility-node";
static NSMutableDictionary<NSString *, NSValue *> *originalChildrenImplementations;
static GThread *gtkMainThread;
static std::thread::id gtkMainStdThread;
static bool AXDebugEnabled() {
  const char *value = std::getenv("EASYHYBRID3_AX_DEBUG");
  return value && std::strcmp(value, "1") == 0;
}

static void AXTrace(const char *event, GtkWidget *widget, const char *value) {
  if (!AXDebugEnabled()) return;
  fprintf(stderr,
          "[EH3-AX] event=%s widget=%p thread=%p gtk-main=%p context-owner=%s value=%s\n",
          event, widget, g_thread_self(), gtkMainThread,
          g_main_context_is_owner(g_main_context_default()) ? "yes" : "no",
          value ? value : "<none>");
  fflush(stderr);
}

typedef struct {
  GtkWidget *widget;
  AtkObject *accessible;
} PressRequest;
typedef struct {
  GtkWidget *widget;
  gchar *value;
  std::shared_ptr<struct ValueCompletion> completion;
} ValueRequest;
struct ValueCompletion {
  std::mutex mutex;
  std::condition_variable condition;
  bool complete = false;
  bool applied = false;
};

@interface EH3AccessibilityNode : NSAccessibilityElement {
  GtkWidget *_widget;
  AtkObject *_accessible;
  __weak NSView *_parentView;
  NSString *_role;
  NSString *_label;
  NSString *_help;
  NSString *_value;
  NSRect _screenFrame;
  BOOL _enabled;
  BOOL _visible;
  BOOL _focused;
}
- (instancetype)initWithWidget:(GtkWidget *)widget accessible:(AtkObject *)accessible parent:(NSView *)parent;
- (void)refreshFromGtk;
@end

@implementation EH3AccessibilityNode
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
  if (!_widget || !_accessible) {
    _enabled = NO;
    _visible = NO;
    return;
  }
  AtkRole atkRole = atk_object_get_role(_accessible);
  const gchar *roleName = atk_role_get_name(atkRole);
  const gchar *name = atk_object_get_name(_accessible);
  const gchar *description = atk_object_get_description(_accessible);
  _role = [NSString stringWithUTF8String:roleName ?: "unknown"];
  _label = [NSString stringWithUTF8String:name ?: ""];
  _help = [NSString stringWithUTF8String:description ?: ""];
  GtkWidget *toplevel = gtk_widget_get_toplevel(_widget);
  _enabled = gtk_widget_is_sensitive(_widget);
  _visible = gtk_widget_get_visible(_widget) && GTK_IS_WIDGET(toplevel) && gtk_widget_get_visible(toplevel);
  _focused = gtk_widget_has_focus(_widget);
  if (GTK_IS_EDITABLE(_widget))
    _value = [NSString stringWithUTF8String:gtk_entry_get_text(GTK_ENTRY(_widget)) ?: ""];
  else if (GTK_IS_TOGGLE_BUTTON(_widget))
    _value = gtk_toggle_button_get_active(GTK_TOGGLE_BUTTON(_widget)) ? @"1" : @"0";
  else if (GTK_IS_COMBO_BOX_TEXT(_widget)) {
    gchar *active = gtk_combo_box_text_get_active_text(GTK_COMBO_BOX_TEXT(_widget));
    _value = active ? [NSString stringWithUTF8String:active] : @"";
    g_free(active);
  } else if (GTK_IS_COMBO_BOX(_widget)) {
    _value = nil;
  } else if (GTK_IS_SPIN_BUTTON(_widget))
    _value = [NSString stringWithFormat:@"%.8g", gtk_spin_button_get_value(GTK_SPIN_BUTTON(_widget))];
  else
    _value = nil;

  AtkRectangle extents = {0};
  if (ATK_IS_COMPONENT(_accessible)) {
    atk_component_get_extents(ATK_COMPONENT(_accessible), &extents.x, &extents.y,
                              &extents.width, &extents.height, ATK_XY_SCREEN);
    NSScreen *screen = _parentView.window.screen ?: NSScreen.mainScreen;
    _screenFrame = NSMakeRect(extents.x, NSMaxY(screen.frame) - (extents.y + extents.height),
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

- (NSString *)accessibilityRole {
  if (GTK_IS_TOOL_BUTTON(_widget) || GTK_IS_TOOL_ITEM(_widget)) return NSAccessibilityButtonRole;
  if (GTK_IS_RADIO_BUTTON(_widget)) return NSAccessibilityRadioButtonRole;
  if (GTK_IS_BUTTON(_widget) && GTK_IS_TOGGLE_BUTTON(_widget)) return NSAccessibilityCheckBoxRole;
  if (GTK_IS_BUTTON(_widget)) return NSAccessibilityButtonRole;
  if (GTK_IS_ENTRY(_widget)) return NSAccessibilityTextFieldRole;
  if (GTK_IS_LABEL(_widget)) return NSAccessibilityStaticTextRole;
  if (GTK_IS_COMBO_BOX(_widget)) return NSAccessibilityPopUpButtonRole;
  if (GTK_IS_SPIN_BUTTON(_widget) || GTK_IS_SCALE(_widget)) return NSAccessibilitySliderRole;
  if (GTK_IS_NOTEBOOK(_widget)) return NSAccessibilityTabGroupRole;
  if (GTK_IS_TREE_VIEW(_widget)) return NSAccessibilityTableRole;
  if (GTK_IS_MENU_ITEM(_widget)) return NSAccessibilityMenuItemRole;
  if (GTK_IS_DIALOG(_widget)) return NSAccessibilityWindowRole;
  if (GTK_IS_WINDOW(_widget)) return NSAccessibilityWindowRole;
  return NSAccessibilityGroupRole;
}
- (NSString *)accessibilityTitle { return _label; }
- (NSString *)accessibilityLabel { return _label; }
- (NSString *)accessibilityHelp { return _help; }
- (NSString *)accessibilityValue {
  if (_widget && GTK_IS_ENTRY(_widget)) {
    const gchar *liveValue = gtk_entry_get_text(GTK_ENTRY(_widget));
    _value = [NSString stringWithUTF8String:liveValue ?: ""];
  }
  return _value;
}
- (NSRect)accessibilityFrame { return _screenFrame; }
- (id)accessibilityParent { return _parentView; }
- (BOOL)isAccessibilityElement { return YES; }
- (BOOL)isAccessibilityEnabled { return _enabled && _visible && _widget != NULL; }
- (BOOL)isAccessibilityHidden { return !_visible; }
- (BOOL)isAccessibilityFocused { return _focused; }
- (void)applyAccessibilityTextValue:(id)value {
  NSString *requested = [value isKindOfClass:[NSString class]] ? (NSString *)value : nil;
  AXTrace("set-value-enter", _widget, requested.UTF8String);
  if (!_widget || !requested || !GTK_IS_ENTRY(_widget) || !ATK_IS_EDITABLE_TEXT(_accessible)) {
    AXTrace("set-value-rejected", _widget, requested.UTF8String);
    return;
  }
  ValueRequest *request = g_new0(ValueRequest, 1);
  new (request) ValueRequest();
  request->widget = _widget;
  request->completion = std::make_shared<ValueCompletion>();
  g_object_add_weak_pointer(G_OBJECT(request->widget), (gpointer *)&request->widget);
  request->value = g_strdup(requested.UTF8String);
  AXTrace("set-value-queued", _widget, request->value);
  auto updateValue = [](gpointer data) -> gboolean {
    ValueRequest *change = static_cast<ValueRequest *>(data);
    AXTrace("set-value-main-context-enter", change->widget, change->value);
    if (change->widget && GTK_IS_ENTRY(change->widget)) {
      AtkObject *accessible = gtk_widget_get_accessible(change->widget);
      if (ATK_IS_EDITABLE_TEXT(accessible)) {
        AXTrace("atk-set-text-contents-enter", change->widget, change->value);
        atk_editable_text_set_text_contents(ATK_EDITABLE_TEXT(accessible), change->value);
        AXTrace("atk-set-text-contents-return", change->widget,
                gtk_entry_get_text(GTK_ENTRY(change->widget)));
        AXTrace(g_strcmp0(gtk_entry_get_text(GTK_ENTRY(change->widget)), change->value) == 0
                    ? "atk-editable-set-matched" : "atk-editable-set-mismatch",
                change->widget, gtk_entry_get_text(GTK_ENTRY(change->widget)));
        if (g_strcmp0(gtk_entry_get_text(GTK_ENTRY(change->widget)), change->value) != 0) {
          AXTrace("atk-editable-fallback-gtk-entry", change->widget, change->value);
          gtk_entry_set_text(GTK_ENTRY(change->widget), change->value);
        }
        AXTrace("set-value-main-context-exit", change->widget,
                gtk_entry_get_text(GTK_ENTRY(change->widget)));
        change->completion->applied = g_strcmp0(gtk_entry_get_text(GTK_ENTRY(change->widget)), change->value) == 0;
      } else {
        AXTrace("set-value-no-atk-editable-text", change->widget, change->value);
      }
    } else {
      AXTrace("set-value-widget-gone", change->widget, change->value);
    }
    {
      std::lock_guard<std::mutex> lock(change->completion->mutex);
      change->completion->complete = true;
    }
    change->completion->condition.notify_one();
    return G_SOURCE_REMOVE;
  };
  auto releaseRequest = [](gpointer data) {
    ValueRequest *change = static_cast<ValueRequest *>(data);
    if (change->widget) g_object_remove_weak_pointer(G_OBJECT(change->widget), (gpointer *)&change->widget);
    g_free(change->value);
    delete change;
  };
  if (std::this_thread::get_id() == gtkMainStdThread) {
    updateValue(request);
    if (request->widget) g_object_remove_weak_pointer(G_OBJECT(request->widget), (gpointer *)&request->widget);
    g_free(request->value);
    delete request;
  } else {
    // An idle source runs when GTK iterates its default context. Unlike
    // g_main_context_invoke_full(), it cannot opportunistically run on the
    // accessibility caller's thread when that thread acquires the context.
    auto completion = request->completion;
    g_idle_add_full(G_PRIORITY_DEFAULT, updateValue, request, releaseRequest);
    std::unique_lock<std::mutex> lock(completion->mutex);
    bool completed = completion->condition.wait_for(lock, std::chrono::seconds(5), [completion] { return completion->complete; });
    bool applied = completed && completion->applied;
    lock.unlock();
    AXTrace(completed ? (applied ? "set-value-complete" : "set-value-not-applied") : "set-value-timeout",
            _widget, requested.UTF8String);
  }
}
- (BOOL)accessibilityIsAttributeSettable:(NSString *)attribute {
  BOOL settable = _widget && GTK_IS_ENTRY(_widget) &&
                  [attribute isEqualToString:NSAccessibilityValueAttribute] &&
                  ATK_IS_EDITABLE_TEXT(_accessible);
  if (settable) AXTrace("is-value-settable", _widget, "yes");
  return settable;
}
- (BOOL)isAccessibilityAttributeSettable:(NSString *)attribute {
  BOOL settable = _widget && GTK_IS_ENTRY(_widget) &&
                  [attribute isEqualToString:NSAccessibilityValueAttribute] &&
                  ATK_IS_EDITABLE_TEXT(_accessible);
  if (settable) AXTrace("is-value-settable", _widget, "yes");
  return settable;
}
- (void)accessibilitySetValue:(id)value forAttribute:(NSString *)attribute {
  AXTrace("accessibilitySetValue-forAttribute", _widget,
          [attribute isEqualToString:NSAccessibilityValueAttribute] ? "AXValue" : attribute.UTF8String);
  if (![attribute isEqualToString:NSAccessibilityValueAttribute]) return;
  [self applyAccessibilityTextValue:value];
}
- (void)setAccessibilityValue:(id)value {
  AXTrace("setAccessibilityValue", _widget, [value isKindOfClass:[NSString class]] ? [(NSString *)value UTF8String] : "<non-string>");
  [self applyAccessibilityTextValue:value];
}
- (NSArray<NSString *> *)accessibilityActionNames {
  if (GTK_IS_BUTTON(_widget) || GTK_IS_TOOL_BUTTON(_widget) || GTK_IS_MENU_ITEM(_widget) || GTK_IS_TOGGLE_BUTTON(_widget))
    return @[ NSAccessibilityPressAction ];
  if (GTK_IS_NOTEBOOK(_widget)) return @[ NSAccessibilityShowMenuAction ];
  return @[];
}
- (NSString *)accessibilityActionDescription:(NSString *)action {
  return [action isEqualToString:NSAccessibilityPressAction] ? @"Press" : @"";
}
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

static void RefreshNode(GObject *object, GParamSpec *property, gpointer data) {
  (void)object; (void)property;
  [( __bridge EH3AccessibilityNode *)data refreshFromGtk];
}
static void EntryChanged(GtkEditable *editable, gpointer data) {
  AXTrace("gtk-editable-changed", GTK_WIDGET(editable), gtk_entry_get_text(GTK_ENTRY(editable)));
  [( __bridge EH3AccessibilityNode *)data refreshFromGtk];
}
static void ReleaseNode(gpointer data, GClosure *closure) { (void)closure; CFBridgingRelease(data); }

static void WidgetDestroyed(GtkWidget *widget, gpointer data) {
  EH3AccessibilityNode *node = (__bridge EH3AccessibilityNode *)data;
  NSView *view = node.accessibilityParent;
  NSMutableArray *children = objc_getAssociatedObject(view, &kChildrenKey);
  [children removeObjectIdenticalTo:node];
  g_object_set_data(G_OBJECT(widget), kNodeDataKey, NULL);
  NSAccessibilityPostNotification(view, NSAccessibilityLayoutChangedNotification);
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
  if (!class_addMethod(cls, selector, (IMP)EH3AccessibilityChildren, types))
    method_setImplementation(class_getInstanceMethod(cls, selector), (IMP)EH3AccessibilityChildren);
  return YES;
}

static PyObject *bridge_register_widget(PyObject *self, PyObject *arg) {
  (void)self;
  GObject *object = pygobject_get(arg);
  if (!object || !GTK_IS_WIDGET(object)) { PyErr_SetString(PyExc_TypeError, "expected Gtk.Widget"); return NULL; }
  GtkWidget *widget = GTK_WIDGET(object);
  GtkWidget *toplevel = gtk_widget_get_toplevel(widget);
  if (!GTK_IS_WINDOW(toplevel) || !gtk_widget_get_realized(toplevel)) { PyErr_SetString(PyExc_RuntimeError, "widget must belong to a realized Gtk.Window"); return NULL; }
  GdkWindow *gdkWindow = gtk_widget_get_window(toplevel);
  NSWindow *nativeWindow = gdk_quartz_window_get_nswindow(gdkWindow);
  NSView *nativeView = gdk_quartz_window_get_nsview(gdkWindow);
  if (!nativeWindow || !nativeView) { PyErr_SetString(PyExc_RuntimeError, "GDK Quartz native window/view unavailable"); return NULL; }
  AtkObject *accessible = gtk_widget_get_accessible(widget);
  if (!accessible || ((GTK_IS_BUTTON(widget) || GTK_IS_TOOL_BUTTON(widget) || GTK_IS_MENU_ITEM(widget)) && !ATK_IS_ACTION(accessible))) {
    PyErr_SetString(PyExc_RuntimeError, "GTK widget has no usable ATK accessible/action"); return NULL;
  }
  @autoreleasepool {
    if (!originalChildrenImplementations) originalChildrenImplementations = [NSMutableDictionary dictionary];
    EH3AccessibilityNode *existing = (__bridge EH3AccessibilityNode *)g_object_get_data(G_OBJECT(widget), kNodeDataKey);
    if (existing) {
      [existing refreshFromGtk];
      Py_RETURN_NONE;
    }
    InstallChildrenHook(nativeView);
    NSMutableArray *children = objc_getAssociatedObject(nativeView, &kChildrenKey);
    if (!children) children = [NSMutableArray array];
    EH3AccessibilityNode *node = [[EH3AccessibilityNode alloc] initWithWidget:widget accessible:accessible parent:nativeView];
    [children addObject:node];
    objc_setAssociatedObject(nativeView, &kChildrenKey, children, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
    g_object_set_data(G_OBJECT(widget), kNodeDataKey, (__bridge void *)node);
    g_signal_connect_data(widget, "notify", G_CALLBACK(RefreshNode), (gpointer)CFBridgingRetain(node), ReleaseNode, G_CONNECT_DEFAULT);
    if (GTK_IS_ENTRY(widget))
      g_signal_connect_data(widget, "changed", G_CALLBACK(EntryChanged), (gpointer)CFBridgingRetain(node), ReleaseNode, G_CONNECT_DEFAULT);
    g_signal_connect_data(toplevel, "notify::visible", G_CALLBACK(RefreshNode), (gpointer)CFBridgingRetain(node), ReleaseNode, G_CONNECT_DEFAULT);
    g_signal_connect_data(widget, "destroy", G_CALLBACK(WidgetDestroyed), (gpointer)CFBridgingRetain(node), ReleaseNode, G_CONNECT_DEFAULT);
    NSAccessibilityPostNotification(nativeView, NSAccessibilityLayoutChangedNotification);
    // GtkWidget and GdkWindow are GObjects, not Objective-C objects. Passing
    // them to NSLog's %@ formatter makes Foundation message them as NSObject
    // instances and can crash during Objective-C class realization.
    if (AXDebugEnabled()) {
      NSLog(@"EasyHybrid3 accessibility registered widget=%p role=%@ label=%@ native-window=%p",
            widget, node.accessibilityRole, node.accessibilityLabel, nativeWindow);
    }
  }
  Py_RETURN_NONE;
}

static PyObject *bridge_finish_launching(PyObject *self, PyObject *Py_UNUSED(ignored)) {
  (void)self;
  gtkMainThread = g_thread_self();
  gtkMainStdThread = std::this_thread::get_id();
  AXTrace("finish-launching", NULL, NULL);
  @autoreleasepool { [NSApp finishLaunching]; }
  Py_RETURN_NONE;
}

static PyMethodDef methods[] = {
  {"register_widget", (PyCFunction)bridge_register_widget, METH_O, "Expose one GTK widget through its native GDK Quartz view."},
  {"finish_launching", (PyCFunction)bridge_finish_launching, METH_NOARGS, "Initialize AppKit's accessibility application endpoint."},
  {NULL, NULL, 0, NULL}
};
static struct PyModuleDef module = { PyModuleDef_HEAD_INIT, "_gtk3_accessibility", NULL, -1, methods };
PyMODINIT_FUNC PyInit__gtk3_accessibility(void) {
  PyObject *gobjectModule = pygobject_init(-1, -1, -1);
  if (!gobjectModule) return NULL;
  Py_DECREF(gobjectModule);
  return PyModule_Create(&module);
}
