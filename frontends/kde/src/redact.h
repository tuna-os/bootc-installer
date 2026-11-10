#pragma once

// The recovery key must not leave the installer in a log (#337).
//
// fisherman sends the LUKS recovery key once, in a `recovery_key` event on
// stdout. The done page shows it and holds Restart until the user says that
// it is saved. The log file and the clipboard copy of the log are what a
// user attaches to a bug report, so they get the redacted form.
//
// The form is the one every frontend writes, byte for byte:
// shared/progress/recovery-key-cases.json has the cases.

#include <QString>

namespace redact {

// What replaces a key.
extern const QString kPlaceholder;

// `text` (one line or many) without a recovery key. Three forms go: the
// `key` value of a `recovery_key` event, the text after "Recovery key:",
// and `knownKey` wherever a later line repeats it.
QString recoveryKey(const QString &text, const QString &knownKey = QString());

} // namespace redact
