#pragma once

// Target-disk list, backing the disk step's ListView.
//
// The disks are fisherman's: `fisherman probe --json`, eligible disks only,
// in fisherman's order, with fisherman's size labels (shared/probe/README.md).
// Only the presentation is here.

#include "probe.h"

#include <QAbstractListModel>
#include <QString>
#include <qqmlintegration.h>

class DiskModel : public QAbstractListModel
{
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(int count READ rowCount NOTIFY countChanged)
    // Why there are no disks, when the probe failed; empty otherwise.
    Q_PROPERTY(QString error READ error NOTIFY countChanged)

public:
    enum Roles {
        DeviceRole = Qt::UserRole + 1,
        SizeRole,
        ModelRole,
        TransportRole,
        SubtitleRole,
        TitleRole,
        RemovableRole,
    };

    explicit DiskModel(QObject *parent = nullptr);

    int rowCount(const QModelIndex &parent = {}) const override;
    QVariant data(const QModelIndex &index, int role) const override;
    QHash<int, QByteArray> roleNames() const override;

    // Re-runs the probe. Called when the disk step is activated, so a disk
    // plugged in after start-up appears.
    Q_INVOKABLE void refresh();
    Q_INVOKABLE QString deviceAt(int row) const;

    // Replaces the rows with a probe result (refresh(), and the tests).
    void setResult(const probe::Result &result);

    QString error() const { return m_error; }

Q_SIGNALS:
    void countChanged();

private:
    QList<probe::Disk> m_disks;
    QString m_error;
};
