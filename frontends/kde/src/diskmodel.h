#pragma once

// Target-disk list, backing the disk step's ListView.
//
// Same discovery as the Widgets frontend it replaces: `lsblk -J`, filtered to
// type == "disk". Only the presentation moved to QML.

#include <QAbstractListModel>
#include <QString>
#include <qqmlintegration.h>

struct DiskEntry {
    QString device;      // "/dev/nvme0n1"
    QString size;
    QString model;
    QString transport;   // "NVMe", "SATA", ...
};

class DiskModel : public QAbstractListModel
{
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(int count READ rowCount NOTIFY countChanged)

public:
    enum Roles {
        DeviceRole = Qt::UserRole + 1,
        SizeRole,
        ModelRole,
        TransportRole,
        SubtitleRole,
    };

    explicit DiskModel(QObject *parent = nullptr);

    int rowCount(const QModelIndex &parent = {}) const override;
    QVariant data(const QModelIndex &index, int role) const override;
    QHash<int, QByteArray> roleNames() const override;

    // Re-runs lsblk. Called when the disk step is activated, mirroring the old
    // DiskSelectionPage::prepare().
    Q_INVOKABLE void refresh();
    Q_INVOKABLE QString deviceAt(int row) const;

Q_SIGNALS:
    void countChanged();

private:
    QList<DiskEntry> m_disks;
};
