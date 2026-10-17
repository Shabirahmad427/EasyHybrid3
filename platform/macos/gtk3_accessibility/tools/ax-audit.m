#import <AppKit/AppKit.h>
#import <ApplicationServices/ApplicationServices.h>
#import <CoreGraphics/CoreGraphics.h>
#import <Security/Security.h>
#include <unistd.h>

static NSString *AXErrorName(AXError error) {
    switch (error) {
        case kAXErrorSuccess: return @"success";
        case kAXErrorFailure: return @"failure";
        case kAXErrorIllegalArgument: return @"illegal-argument";
        case kAXErrorInvalidUIElement: return @"invalid-ui-element";
        case kAXErrorInvalidUIElementObserver: return @"invalid-observer";
        case kAXErrorCannotComplete: return @"cannot-complete";
        case kAXErrorAttributeUnsupported: return @"attribute-unsupported";
        case kAXErrorActionUnsupported: return @"action-unsupported";
        case kAXErrorNotificationUnsupported: return @"notification-unsupported";
        case kAXErrorNotImplemented: return @"not-implemented";
        case kAXErrorNotificationAlreadyRegistered: return @"notification-already-registered";
        case kAXErrorNotificationNotRegistered: return @"notification-not-registered";
        case kAXErrorAPIDisabled: return @"api-disabled";
        case kAXErrorNoValue: return @"no-value";
        case kAXErrorParameterizedAttributeUnsupported: return @"parameterized-attribute-unsupported";
        case kAXErrorNotEnoughPrecision: return @"not-enough-precision";
        default: return [NSString stringWithFormat:@"unknown-%d", error];
    }
}

static id AXValue(AXUIElementRef element, CFStringRef attribute, AXError *outError) {
    CFTypeRef value = NULL;
    AXError error = AXUIElementCopyAttributeValue(element, attribute, &value);
    if (outError) *outError = error;
    if (error != kAXErrorSuccess || value == NULL) return nil;
    return CFBridgingRelease(value);
}

static NSString *AXText(AXUIElementRef element, CFStringRef attribute) {
    AXError error = kAXErrorSuccess;
    id value = AXValue(element, attribute, &error);
    if (error != kAXErrorSuccess) return [NSString stringWithFormat:@"<%@:%d>", AXErrorName(error), error];
    return [value description] ?: @"<null>";
}

static void PrintTree(AXUIElementRef element, int depth, int *buttonCount,
                      NSString *targetLabel, AXUIElementRef *targetButton) {
    if (depth > 8) return;
    NSString *role = AXText(element, kAXRoleAttribute);
    NSString *title = AXText(element, kAXTitleAttribute);
    NSString *description = AXText(element, kAXDescriptionAttribute);
    NSString *value = AXText(element, kAXValueAttribute);
    NSString *enabled = AXText(element, kAXEnabledAttribute);
    NSString *indent = [@"" stringByPaddingToLength:(NSUInteger)depth * 2 withString:@" " startingAtIndex:0];
    fprintf(stdout, "%sNODE role=%s title=%s description=%s value=%s enabled=%s\n", indent.UTF8String,
            role.UTF8String, title.UTF8String, description.UTF8String, value.UTF8String, enabled.UTF8String);

    if ([role isEqualToString:(__bridge NSString *)kAXButtonRole]) (*buttonCount)++;
    if ([role isEqualToString:(__bridge NSString *)kAXButtonRole] ||
        [role isEqualToString:(__bridge NSString *)kAXMenuItemRole]) {
        if (targetButton && *targetButton == NULL && targetLabel &&
            ([title isEqualToString:targetLabel] || [description isEqualToString:targetLabel])) {
            *targetButton = (AXUIElementRef)CFRetain(element);
            fprintf(stdout, "%s  TARGET position=%s size=%s\n", indent.UTF8String,
                    AXText(element, kAXPositionAttribute).UTF8String,
                    AXText(element, kAXSizeAttribute).UTF8String);
        }
    }
    if ([role isEqualToString:(__bridge NSString *)kAXButtonRole] ||
        [role isEqualToString:(__bridge NSString *)kAXMenuItemRole]) {
        CFArrayRef actions = NULL;
        AXError error = AXUIElementCopyActionNames(element, &actions);
        fprintf(stdout, "%s  ACTIONS error=%s(%d) names=%s\n", indent.UTF8String,
                AXErrorName(error).UTF8String, error,
                actions ? [(__bridge NSArray *)actions description].UTF8String : "<none>");
        if (actions) CFRelease(actions);
    }

    CFTypeRef childrenValue = NULL;
    AXError childrenError = AXUIElementCopyAttributeValue(element, kAXChildrenAttribute, &childrenValue);
    if (childrenError != kAXErrorSuccess) {
        fprintf(stdout, "%s  CHILDREN error=%s(%d)\n", indent.UTF8String,
                AXErrorName(childrenError).UTF8String, childrenError);
        return;
    }
    NSArray *children = CFBridgingRelease(childrenValue);
    for (id child in children) {
        if (CFGetTypeID((__bridge CFTypeRef)child) == AXUIElementGetTypeID())
            PrintTree((__bridge AXUIElementRef)child, depth + 1, buttonCount, targetLabel, targetButton);
    }
}

static AXUIElementRef FindButton(AXUIElementRef element, NSString *label, int depth) {
    if (depth > 12) return NULL;
    NSString *role = AXText(element, kAXRoleAttribute);
    if ([role isEqualToString:(__bridge NSString *)kAXButtonRole] ||
        [role isEqualToString:(__bridge NSString *)kAXMenuItemRole]) {
        NSString *title = AXText(element, kAXTitleAttribute);
        NSString *description = AXText(element, kAXDescriptionAttribute);
        if ([title isEqualToString:label] || [description isEqualToString:label])
            return (AXUIElementRef)CFRetain(element);
    }
    CFTypeRef childrenValue = NULL;
    AXError error = AXUIElementCopyAttributeValue(element, kAXChildrenAttribute, &childrenValue);
    if (error != kAXErrorSuccess || !childrenValue) return NULL;
    NSArray *children = CFBridgingRelease(childrenValue);
    for (id child in children) {
        if (CFGetTypeID((__bridge CFTypeRef)child) != AXUIElementGetTypeID()) continue;
        AXUIElementRef found = FindButton((__bridge AXUIElementRef)child, label, depth + 1);
        if (found) return found;
    }
    return NULL;
}

static AXUIElementRef FindTextFieldWithValue(AXUIElementRef element, NSString *value, int depth);
static AXUIElementRef WaitForButton(AXUIElementRef root, NSString *label, int attempts);
static BOOL WindowExists(AXUIElementRef app, NSString *title);
static AXUIElementRef FindLastTextField(AXUIElementRef element, int depth, AXUIElementRef *last);

static AXUIElementRef FindWindow(AXUIElementRef app, NSString *title) {
    CFTypeRef raw = NULL;
    if (AXUIElementCopyAttributeValue(app, kAXWindowsAttribute, &raw) != kAXErrorSuccess || !raw) return NULL;
    NSArray *windows = CFBridgingRelease(raw);
    for (id item in windows) {
        AXUIElementRef window = (__bridge AXUIElementRef)item;
        if ([AXText(window, kAXTitleAttribute) isEqualToString:title]) return (AXUIElementRef)CFRetain(window);
    }
    return NULL;
}

static BOOL PressAndWaitForWindow(AXUIElementRef app, NSString *buttonName, NSString *windowTitle, BOOL shouldAppear) {
    AXUIElementRef button = FindButton(app, buttonName, 0);
    if (!button) {
        fprintf(stdout, "DIALOG button=%s result=missing\n", buttonName.UTF8String);
        return NO;
    }
    AXError action = AXUIElementPerformAction(button, kAXPressAction);
    CFRelease(button);
    if (!shouldAppear) {
        fprintf(stdout, "DIALOG action=%s title=%s cancel-error=%s(%d)\n",
                buttonName.UTF8String, windowTitle.UTF8String, AXErrorName(action).UTF8String, action);
        return action == kAXErrorSuccess;
    }
    AXUIElementRef dialog = NULL;
    for (int i = 0; i < 80; i++) {
        usleep(100000);
        dialog = FindWindow(app, windowTitle);
        if ((dialog != NULL) == shouldAppear) break;
        if (dialog) { CFRelease(dialog); dialog = NULL; }
    }
    BOOL observed = (dialog != NULL) == shouldAppear;
    fprintf(stdout, "DIALOG action=%s title=%s action-error=%s(%d) expected=%s observed=%s\n",
            buttonName.UTF8String, windowTitle.UTF8String, AXErrorName(action).UTF8String, action,
            shouldAppear ? "present" : "absent", observed ? "yes" : "no");
    if (dialog) CFRelease(dialog);
    return action == kAXErrorSuccess && observed;
}

static BOOL RunDialogCycles(AXUIElementRef app, int cycles) {
    BOOL ok = YES;
    for (int i = 0; i < cycles; i++) {
        fprintf(stdout, "DIALOG_CYCLE index=%d\n", i + 1);
        ok &= PressAndWaitForWindow(app, @"Open", @"Open File...", YES);
        if (FindWindow(app, @"Open File...")) {
            AXUIElementRef dialog = FindWindow(app, @"Open File...");
            AXUIElementRef cancel = dialog ? WaitForButton(dialog, @"Cancel", 50) : NULL;
            if (cancel) { AXError e = AXUIElementPerformAction(cancel, kAXPressAction); fprintf(stdout, "DIALOG_CANCEL title=Open File... error=%s(%d)\n", AXErrorName(e).UTF8String, e); if (e != kAXErrorSuccess) ok = NO; CFRelease(cancel); }
            else { fprintf(stdout, "DIALOG_CANCEL title=Open File... result=missing\n"); ok = NO; }
            if (dialog) CFRelease(dialog);
            for (int wait = 0; wait < 80 && WindowExists(app, @"Open File..."); wait++) usleep(100000);
            AXUIElementRef staleOpen = FindWindow(app, @"Open File...");
            fprintf(stdout, "AX_CLEANUP title=Open File... removed=%s\n", staleOpen ? "no" : "yes");
            if (staleOpen) { ok = NO; CFRelease(staleOpen); }
        } else ok = NO;
        ok &= PressAndWaitForWindow(app, @"New Project", @"Import New System", YES);
        AXUIElementRef newDialog = FindWindow(app, @"Import New System");
        if (newDialog) {
            AXUIElementRef field = NULL;
            for (int attempt = 0; attempt < 80 && !field; attempt++) {
                FindLastTextField(newDialog, 0, &field);
                if (!field) usleep(100000);
            }
            if (field) {
                NSString *test = [NSString stringWithFormat:@"AX_TEST_123_%d", i + 1];
                fprintf(stdout, "TEXT_EDIT before=%s\n", AXText(field, kAXValueAttribute).UTF8String);
                AXError setError = AXUIElementSetAttributeValue(field, kAXValueAttribute, (__bridge CFTypeRef)test);
                usleep(250000);
                NSString *actual = AXText(field, kAXValueAttribute);
                fprintf(stdout, "TEXT_EDIT cycle=%d error=%s(%d) expected=%s actual=%s match=%s\n", i + 1,
                        AXErrorName(setError).UTF8String, setError, test.UTF8String, actual.UTF8String,
                        [actual isEqualToString:test] ? "yes" : "no");
                if (![actual isEqualToString:test]) ok = NO;
                CFRelease(field);
            } else { fprintf(stdout, "TEXT_EDIT cycle=%d generated-tag-field=missing\n", i + 1); ok = NO; }
            AXUIElementRef cancel = WaitForButton(newDialog, @"Cancel", 50);
            if (cancel) { AXError e = AXUIElementPerformAction(cancel, kAXPressAction); fprintf(stdout, "DIALOG_CANCEL title=Import New System error=%s(%d)\n", AXErrorName(e).UTF8String, e); if (e != kAXErrorSuccess) ok = NO; CFRelease(cancel); }
            else { fprintf(stdout, "DIALOG_CANCEL title=Import New System result=missing\n"); ok = NO; }
            CFRelease(newDialog);
            for (int wait = 0; wait < 80 && WindowExists(app, @"Import New System"); wait++) usleep(100000);
        } else ok = NO;
        AXUIElementRef stale = FindWindow(app, @"Import New System");
        fprintf(stdout, "AX_CLEANUP title=Import New System removed=%s\n", stale ? "no" : "yes");
        if (stale) { ok = NO; CFRelease(stale); }
    }
    return ok;
}

static AXUIElementRef FindTextFieldWithValue(AXUIElementRef element, NSString *value, int depth) {
    if (depth > 12) return NULL;
    NSString *role = AXText(element, kAXRoleAttribute);
    if ([role isEqualToString:(__bridge NSString *)kAXTextFieldRole] &&
        [AXText(element, kAXValueAttribute) isEqualToString:value])
        return (AXUIElementRef)CFRetain(element);
    CFTypeRef childrenValue = NULL;
    AXError error = AXUIElementCopyAttributeValue(element, kAXChildrenAttribute, &childrenValue);
    if (error != kAXErrorSuccess || !childrenValue) return NULL;
    NSArray *children = CFBridgingRelease(childrenValue);
    for (id child in children) {
        if (CFGetTypeID((__bridge CFTypeRef)child) != AXUIElementGetTypeID()) continue;
        AXUIElementRef found = FindTextFieldWithValue((__bridge AXUIElementRef)child, value, depth + 1);
        if (found) return found;
    }
    return NULL;
}

static AXUIElementRef WaitForButton(AXUIElementRef root, NSString *label, int attempts) {
    for (int i = 0; i < attempts; i++) {
        AXUIElementRef found = FindButton(root, label, 0);
        if (found) return found;
        usleep(100000);
    }
    return NULL;
}

static BOOL WindowExists(AXUIElementRef app, NSString *title) {
    AXUIElementRef window = FindWindow(app, title);
    BOOL exists = window != NULL;
    if (window) CFRelease(window);
    return exists;
}

static AXUIElementRef FindLastTextField(AXUIElementRef element, int depth, AXUIElementRef *last) {
    if (depth > 12) return NULL;
    if ([AXText(element, kAXRoleAttribute) isEqualToString:(__bridge NSString *)kAXTextFieldRole]) {
        if (*last) CFRelease(*last);
        *last = (AXUIElementRef)CFRetain(element);
    }
    CFTypeRef raw = NULL;
    if (AXUIElementCopyAttributeValue(element, kAXChildrenAttribute, &raw) != kAXErrorSuccess || !raw) return *last;
    NSArray *children = CFBridgingRelease(raw);
    for (id child in children) {
        if (CFGetTypeID((__bridge CFTypeRef)child) == AXUIElementGetTypeID())
            FindLastTextField((__bridge AXUIElementRef)child, depth + 1, last);
    }
    return *last;
}

static void InspectApplication(pid_t pid, NSString *label, NSString *pressLabel, BOOL lifecycle,
                               NSString *setFromValue, NSString *setValue, BOOL activate) {
    NSRunningApplication *running = [NSRunningApplication runningApplicationWithProcessIdentifier:pid];
    fprintf(stdout, "APPLICATION label=%s pid=%d\n", label.UTF8String, pid);
    if (running && activate)
        [running activateWithOptions:NSApplicationActivateAllWindows];
    if (running) {
        fprintf(stdout, "RUNNING_APP bundle=%s name=%s activation-policy=%ld active=%s hidden=%s terminated=%s\n",
                (running.bundleIdentifier ?: @"<none>").UTF8String,
                (running.localizedName ?: @"<none>").UTF8String,
                (long)running.activationPolicy,
                running.active ? "yes" : "no", running.hidden ? "yes" : "no",
                running.terminated ? "yes" : "no");
    }
    AXUIElementRef app = AXUIElementCreateApplication(pid);
    AXUIElementSetMessagingTimeout(app, 15.0f);
    fprintf(stdout, "APP_ROLE=%s APP_TITLE=%s APP_DESCRIPTION=%s\n",
            AXText(app, kAXRoleAttribute).UTF8String,
            AXText(app, kAXTitleAttribute).UTF8String,
            AXText(app, kAXDescriptionAttribute).UTF8String);
    AXError error = kAXErrorSuccess;
    id windowsValue = AXValue(app, kAXWindowsAttribute, &error);
    fprintf(stdout, "WINDOWS error=%s(%d) value=%s\n", AXErrorName(error).UTF8String, error,
            windowsValue ? [windowsValue description].UTF8String : "<none>");
    if (error == kAXErrorSuccess) {
        int buttons = 0;
        AXUIElementRef firstButton = NULL;
        NSArray *windows = windowsValue;
        for (id window in windows)
            PrintTree((__bridge AXUIElementRef)window, 0, &buttons, pressLabel, &firstButton);
        fprintf(stdout, "BUTTON_COUNT=%d\n", buttons);
        fprintf(stdout, "TARGET_BUTTON_FOUND=%s\n", firstButton ? "yes" : "no");
        if (pressLabel && firstButton) {
            AXError pressError = AXUIElementPerformAction(firstButton, kAXPressAction);
            fprintf(stdout, "AXPRESS error=%s(%d)\n", AXErrorName(pressError).UTF8String, pressError);
            if (lifecycle && pressError == kAXErrorSuccess) {
                usleep(300000);
                CFTypeRef hiddenValue = NULL;
                AXError hiddenError = AXUIElementCopyAttributeValue(app, kAXWindowsAttribute, &hiddenValue);
                NSArray *hiddenWindows = hiddenError == kAXErrorSuccess ? CFBridgingRelease(hiddenValue) : @[];
                fprintf(stdout, "LIFECYCLE phase=hidden windows-error=%s(%d) count=%lu\n",
                        AXErrorName(hiddenError).UTF8String, hiddenError, (unsigned long)hiddenWindows.count);

                usleep(1400000);
                CFTypeRef shownValue = NULL;
                AXError shownError = AXUIElementCopyAttributeValue(app, kAXWindowsAttribute, &shownValue);
                NSArray *shownWindows = shownError == kAXErrorSuccess ? CFBridgingRelease(shownValue) : @[];
                fprintf(stdout, "LIFECYCLE phase=shown windows-error=%s(%d) count=%lu\n",
                        AXErrorName(shownError).UTF8String, shownError, (unsigned long)shownWindows.count);
                AXUIElementRef shownButton = NULL;
                for (id item in shownWindows) {
                    AXUIElementRef afterWindow = (__bridge AXUIElementRef)item;
                    fprintf(stdout, "  WINDOW title=%s hidden=%s\n",
                            AXText(afterWindow, kAXTitleAttribute).UTF8String,
                            AXText(afterWindow, kAXHiddenAttribute).UTF8String);
                    if (!shownButton) shownButton = FindButton(afterWindow, @"Run accessible button", 0);
                }
                fprintf(stdout, "LIFECYCLE button-after-show=%s\n", shownButton ? "found" : "missing");
                if (shownButton) {
                    AXError closePress = AXUIElementPerformAction(shownButton, kAXPressAction);
                    fprintf(stdout, "AXPRESS_CLOSE error=%s(%d)\n", AXErrorName(closePress).UTF8String, closePress);
                    CFRelease(shownButton);
                    usleep(500000);
                    CFTypeRef closeValue = NULL;
                    AXError closeError = AXUIElementCopyAttributeValue(app, kAXWindowsAttribute, &closeValue);
                    if (closeValue) CFRelease(closeValue);
                    fprintf(stdout, "AFTER_CLOSE windows-error=%s(%d)\n", AXErrorName(closeError).UTF8String, closeError);
                }
            }
            CFRelease(firstButton);
        }
        if (setFromValue && setValue) {
            AXUIElementRef field = NULL;
            for (id window in windows) {
                field = FindTextFieldWithValue((__bridge AXUIElementRef)window, setFromValue, 0);
                if (field) break;
            }
            fprintf(stdout, "TARGET_TEXT_FIELD_FOUND=%s\n", field ? "yes" : "no");
            if (field) {
                Boolean settable = false;
                AXError settableError = AXUIElementIsAttributeSettable(field, kAXValueAttribute, &settable);
                fprintf(stdout, "AXVALUE_SETTABLE error=%s(%d) settable=%s\n",
                        AXErrorName(settableError).UTF8String, settableError, settable ? "yes" : "no");
                AXError setError = settable && settableError == kAXErrorSuccess
                    ? AXUIElementSetAttributeValue(field, kAXValueAttribute, (__bridge CFTypeRef)setValue)
                    : kAXErrorActionUnsupported;
                fprintf(stdout, "AXSETVALUE error=%s(%d)\n", AXErrorName(setError).UTF8String, setError);
                usleep(300000);
                fprintf(stdout, "AXVALUE_AFTER_SET=%s\n", AXText(field, kAXValueAttribute).UTF8String);
                CFRelease(field);
            }
        }
    }
    CFRelease(app);

    CFArrayRef infoValue = CGWindowListCopyWindowInfo(kCGWindowListOptionAll, kCGNullWindowID);
    NSArray *windowInfo = infoValue ? CFBridgingRelease(infoValue) : @[];
    NSUInteger matchingWindows = 0;
    for (NSDictionary *window in windowInfo) {
        if ([window[(id)kCGWindowOwnerPID] intValue] != pid) continue;
        matchingWindows++;
        fprintf(stdout, "CGWINDOW owner=%s title=%s layer=%s bounds=%s\n",
                [window[(id)kCGWindowOwnerName] description].UTF8String ?: "",
                [window[(id)kCGWindowName] description].UTF8String ?: "<none>",
                [window[(id)kCGWindowLayer] description].UTF8String ?: "<none>",
                [window[(id)kCGWindowBounds] description].UTF8String ?: "<none>");
    }
    fprintf(stdout, "CGWINDOW_MATCHES=%lu\n", (unsigned long)matchingWindows);
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        BOOL prompt = NO;
        BOOL lifecycle = NO;
        BOOL targetOnly = NO;
        BOOL activate = NO;
        BOOL closeWindow = NO;
        int dialogCycles = 0;
        NSString *pressLabel = nil;
        NSString *setFromValue = nil;
        NSString *setValue = nil;
        pid_t targetPID = 0;
        for (int i = 1; i < argc; i++) {
            if (strcmp(argv[i], "--prompt") == 0) prompt = YES;
            else if (strcmp(argv[i], "--target-only") == 0) targetOnly = YES;
            else if (strcmp(argv[i], "--activate") == 0) activate = YES;
            else if (strcmp(argv[i], "--close-window") == 0) closeWindow = YES;
            else if (strcmp(argv[i], "--dialog-cycles") == 0 && i + 1 < argc) dialogCycles = (int)strtol(argv[++i], NULL, 10);
            else if (strcmp(argv[i], "--press-first-button") == 0) {
                pressLabel = @"Run accessible button";
                lifecycle = YES;
            }
            else if (strcmp(argv[i], "--press-label") == 0 && i + 1 < argc)
                pressLabel = [NSString stringWithUTF8String:argv[++i]];
            else if (strcmp(argv[i], "--set-from-value") == 0 && i + 1 < argc)
                setFromValue = [NSString stringWithUTF8String:argv[++i]];
            else if (strcmp(argv[i], "--set-value") == 0 && i + 1 < argc)
                setValue = [NSString stringWithUTF8String:argv[++i]];
            else if (strcmp(argv[i], "--pid") == 0 && i + 1 < argc) targetPID = (pid_t)strtol(argv[++i], NULL, 10);
        }

        NSDictionary *options = @{(__bridge NSString *)kAXTrustedCheckOptionPrompt: @(prompt)};
        BOOL trusted = AXIsProcessTrustedWithOptions((__bridge CFDictionaryRef)options);
        NSRunningApplication *selfApp = NSRunningApplication.currentApplication;
        SecCodeRef selfCode = NULL;
        CFDictionaryRef signingInfo = NULL;
        NSString *signingID = @"<unsigned-or-unavailable>";
        if (SecCodeCopySelf(kSecCSDefaultFlags, &selfCode) == errSecSuccess &&
            SecCodeCopySigningInformation(selfCode, kSecCSSigningInformation, &signingInfo) == errSecSuccess) {
            id identifier = CFDictionaryGetValue(signingInfo, kSecCodeInfoIdentifier);
            if (identifier) signingID = [identifier description];
        }
        fprintf(stdout, "CLIENT trusted=%s pid=%d bundle=%s name=%s signed=%s\n",
                trusted ? "yes" : "no", getpid(), (selfApp.bundleIdentifier ?: @"<none>").UTF8String,
                (selfApp.localizedName ?: @"<none>").UTF8String,
                signingID.UTF8String);
        if (signingInfo) CFRelease(signingInfo);
        if (selfCode) CFRelease(selfCode);

        if (!targetOnly) {
            for (NSRunningApplication *app in NSWorkspace.sharedWorkspace.runningApplications) {
                if ([app.bundleIdentifier isEqualToString:@"com.apple.systempreferences"]) {
                    InspectApplication(app.processIdentifier, @"known-native-System-Settings", nil, NO, nil, nil, NO);
                    break;
                }
            }
            for (NSRunningApplication *app in NSWorkspace.sharedWorkspace.runningApplications) {
                if ([app.bundleIdentifier isEqualToString:@"com.apple.finder"]) {
                    InspectApplication(app.processIdentifier, @"known-native-Finder", nil, NO, nil, nil, NO);
                    break;
                }
            }
        }
        BOOL testPassed = YES;
        if (targetPID > 0) {
            if (dialogCycles > 0) {
                AXUIElementRef app = AXUIElementCreateApplication(targetPID);
                AXUIElementSetMessagingTimeout(app, 15.0f);
                testPassed = RunDialogCycles(app, dialogCycles);
                fprintf(stdout, "DIALOG_TEST_RESULT=%s\n", testPassed ? "PASS" : "FAIL");
                CFRelease(app);
                return testPassed ? 0 : 1;
            }
            if (closeWindow) {
                AXUIElementRef app = AXUIElementCreateApplication(targetPID);
                CFTypeRef rawWindows = NULL;
                AXError windowsError = AXUIElementCopyAttributeValue(app, kAXWindowsAttribute, &rawWindows);
                NSArray *windows = windowsError == kAXErrorSuccess && rawWindows ? CFBridgingRelease(rawWindows) : @[];
                AXUIElementRef mainWindow = NULL;
                for (id item in windows) {
                    AXUIElementRef window = (__bridge AXUIElementRef)item;
                    if ([AXText(window, kAXTitleAttribute) isEqualToString:@"EasyHybrid 3.1.3"]) {
                        mainWindow = window; break;
                    }
                }
                CFTypeRef rawClose = NULL;
                AXError closeAttr = mainWindow ? AXUIElementCopyAttributeValue(mainWindow, kAXCloseButtonAttribute, &rawClose) : kAXErrorNoValue;
                AXError closeAction = closeAttr == kAXErrorSuccess && rawClose
                    ? AXUIElementPerformAction((AXUIElementRef)rawClose, kAXPressAction) : closeAttr;
                fprintf(stdout, "WINDOW_CLOSE window-found=%s attribute=%s(%d) action=%s(%d)\n",
                        mainWindow ? "yes" : "no", AXErrorName(closeAttr).UTF8String, closeAttr,
                        AXErrorName(closeAction).UTF8String, closeAction);
                if (rawClose) CFRelease(rawClose);
                CFRelease(app);
                return closeAction == kAXErrorSuccess ? 0 : 1;
            }
            InspectApplication(targetPID, @"Accessibility-target", pressLabel, lifecycle,
                               setFromValue, setValue, activate);
        } else {
            for (NSRunningApplication *app in NSWorkspace.sharedWorkspace.runningApplications) {
                if ([app.bundleIdentifier isEqualToString:@"org.python.python"])
                    InspectApplication(app.processIdentifier, @"Python-process", pressLabel, lifecycle,
                                       setFromValue, setValue, activate);
            }
        }
    }
    return 0;
}
