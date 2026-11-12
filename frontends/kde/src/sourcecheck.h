#pragma once

// The source check (#266), the live host's bootc storage (#267) and the
// boot verification result (#269): a port of the canonical Python readers,
// shared/python/bootc_shared/source_check.py and completion.py.
//
// fisherman owns the facts (fisherman/docs/PROBE.md, docs/RECEIPT.md).
// These readers only turn its answer into a state and the copy keys that
// shared/probe/README.md ("Source check") and shared/completion/README.md
// name. They decide no compatibility rule. tests/test_backend.cpp reads the
// shared case files and must give the same views as the Python reader.
//
// Each view is a QJsonObject with the keys of the case files, so that the
// test compares it whole and QML reads it as a map.

#include <QByteArray>
#include <QJsonObject>
#include <QList>
#include <QPair>
#include <QString>
#include <QStringList>

namespace sourcecheck {

struct Request {
    QString source;      // the recipe's image
    bool liveRoot = false; // the recipe leaves image empty on live media
    QString target;      // the recipe's targetImgref
    QStringList features; // "unified_storage" when the recipe sets unifiedStorage
};

// The request for a recipe as the controller sends it.
Request fromRecipe(const QJsonObject &recipe, bool isLive);

// The arguments after `probe --json` that select the request; empty when
// it names no source.
QStringList probeArguments(const Request &req);

// The views. `ok` false means the probe failed (no output to read).
QJsonObject check(bool ok, const QByteArray &probeOutput, const Request &req);
QJsonObject bootcStore(bool ok, const QByteArray &probeOutput);
QJsonObject verification(const QByteArray &result, const QString &expectedInstallId = QString());

// Only a blocked source holds Install.
bool blocksInstall(const QJsonObject &checkView);

// A registry reference without its docker:// transport.
QString plainRef(const QString &ref);

// fisherman's `receipt` progress event as {state, install_id, reason}
// (shared/progress/receipt-cases.json), and the done page's copy keys for
// it, with the {value} of each (bootc_shared.completion.receipt_lines).
// A null receipt means that no event came.
QJsonObject receiptOf(const QJsonObject &event);
QList<QPair<QString, QString>> receiptLines(const QJsonValue &receipt);

// fisherman's `error` progress event as bootc_shared.progress._error_of()
// keeps it (shared/progress/error-cases.json): message, code, field and
// step_id ("" when missing or not a string), disk_changed (the boolean, else
// null) and cleanup ({status, message}, else null; a status other than ok,
// failed or timed_out is ""). failureLines() are the failure page's copy
// keys for it (bootc_shared.progress.failure_lines, tuna-os/fisherman#449).
QJsonObject errorOf(const QJsonObject &event);
QStringList failureLines(const QJsonObject &error);

// fisherman's `source_reuse` events (#267, shared/progress/source-reuse-cases.json):
// the copy of this computer's system before the first step, as
// bootc_shared.progress.source_reuse_of() keeps it. `view` is the one before
// the event, or null. sourceReuseLines() are the progress page's copy keys
// with the {value} of each; copyCancel() says whether a cancel now leaves
// the disk as it was (no step has started, `step` is the current one).
QJsonValue sourceReuseOf(const QJsonObject &event, const QJsonValue &view);
QList<QPair<QString, QString>> sourceReuseLines(const QJsonValue &view);
bool copyCancel(const QJsonValue &view, int step);

// The install source (#267, shared/probe/source-reuse-cases.json): the item
// of this computer's bootc storage that the install may copy, as {ref,
// digest, platform}, or an empty object. `probeOutput` is the plain probe;
// `updateRef` the recipe's targetImgref. Never on live media.
QJsonObject reuseSource(bool ok, const QByteArray &probeOutput, const QString &updateRef);
// The recipe with that item as its source: an empty image, the update
// reference kept, sourceReuse and the bootc_store_reuse opt-in.
QJsonObject applyReuse(const QJsonObject &recipe, const QJsonObject &source);
// The keys of `validate --json --partial` that check it.
QJsonObject reuseFragment(const QJsonObject &recipe);

}
