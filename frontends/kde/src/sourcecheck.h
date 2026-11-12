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

}
