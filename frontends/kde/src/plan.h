#pragma once

// `fisherman plan --json -` for the confirm step (fisherman/docs/PLAN.md,
// tuna-os/fisherman#371): a port of the canonical Python reader in
// shared/python/bootc_shared/plan.py, held to the same golden plans by
// tests/test_backend.cpp.
//
// A plan says what an install of a recipe would do, before anything is
// written: the target disk and what it reports about itself, and every
// device whose data the install destroys. `plan` needs no root, so it runs
// as `validate` does: unprivileged, through fisherman.h's resolver, with the
// whole recipe on stdin and never on argv (it can hold the LUKS
// passphrase). The plan itself holds no secret.
//
// A plan is not a permission: the install checks the device again. To make
// it refuse a disk that is not the one the user confirmed, the controller
// copies the plan's identity into the recipe as `diskIdentity` (bind()), and
// to make it refuse an install whose plan changed since the user confirmed
// it, the plan's `binding` as `planBinding` (plan_stale). Without a plan (an
// older fisherman, a timeout) the install runs as before.

#include <QByteArray>
#include <QJsonObject>
#include <QList>
#include <QPair>
#include <QString>
#include <QStringList>

namespace branding {
struct Branding;
}

namespace plan {

// The schema version this reader understands (PLAN.md, "Output").
inline constexpr int PROTOCOL_VERSION = 1;
// How long one plan may take: one lsblk call and the TPM. This bounds a
// hung flatpak-spawn or a slow udev.
inline constexpr int TIMEOUT_MS = 20000;
// The value of a field that only the install can resolve.
inline constexpr const char *UNKNOWN = "unknown";

struct Result {
    bool ok = false;        // fisherman answered with a plan result
    QString error;          // why not, when !ok; names no part of the recipe
    bool valid = false;     // the recipe is valid and `plan` is set
    QStringList errorCodes; // fisherman's codes when !valid
    QJsonObject plan;       // empty unless valid
};

// fisherman's arguments; the binary is fisherman.h's unprivileged command.
// The recipe goes on stdin.
QStringList arguments();

// A Result for a plan that could not be had: `why` names no part of the
// recipe.
Result failed(const QString &why);

// Parses `plan --json` output. An older fisherman has no `plan` command;
// whatever it prints instead has no protocol_version and is refused.
Result parse(const QByteArray &json);

// The result of a finished process: exit 0 is a plan, 1 an invalid
// recipe; a crash, another exit code or no answer is an error.
Result fromExit(bool normalExit, int exitCode, const QByteArray &stdoutData,
                const QByteArray &stderrData);

// Runs `argv` with `recipeJson` on its stdin and waits at most `timeoutMs`.
// Blocks: call it off the UI thread.
Result run(const QStringList &argv, const QByteArray &recipeJson, int timeoutMs = TIMEOUT_MS);

// `plan.target.identity`, or {} for a manual layout or no plan.
QJsonObject identity(const QJsonObject &plan);

// The recipe's `diskIdentity`: `serial`, `wwn` and `sizeBytes` of the
// identity, each only when the plan knows it. {} when it knows none.
QJsonObject diskIdentity(const QJsonObject &plan);

// The recipe's `planBinding`: `plan.binding.digest`, and `read_image` as
// `readImage` when it is a boolean (PLAN.md, "plan.binding"). {} when the
// plan has no binding (a fisherman before it) or its digest is not
// `sha256:` and 64 lowercase hex digits.
QJsonObject planBinding(const QJsonObject &plan);

// `recipe` bound to `plan`, or `recipe` unchanged when the plan cannot bind
// it. `diskIdentity` is set when the plan knows an identity of the recipe's
// `disk` (not for a manual layout, an unknown identity or a plan for another
// disk). `planBinding` is set when the plan has a binding and is not for
// another disk than the recipe's `disk`: a manual layout, which has no
// target disk, is still bound to its plan.
QJsonObject bind(const QJsonObject &recipe, const QJsonObject &plan);

// (device, effect) of `plan.destroys`, in fisherman's order.
QList<QPair<QString, QString>> destroys(const QJsonObject &plan);

// The confirm step's rows (title, detail) in the words of the branding's
// confirm_plan_* lines: the target disk and whether the install is bound to
// it, then each device the install destroys. A row whose title the branding
// hides is left out.
using Rows = QList<QPair<QString, QString>>;
Rows targetRows(const QJsonObject &plan, const branding::Branding &copy);
Rows destroyRows(const QJsonObject &plan, const branding::Branding &copy);
Rows rows(const QJsonObject &plan, const branding::Branding &copy);

// fisherman's size rule (binary units), as bootc_shared.probe.format_size:
// the plan's byte count has no size_label.
QString formatSize(qint64 bytes);

}
