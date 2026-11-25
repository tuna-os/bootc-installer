// A wizard step, exposed to QML.
//
// Deliberately a near-copy of KDE KISS's SetupModule
// (https://github.com/KDE/kiss, src/components/setupmodule.h) so that a
// tuna module and a KISS module have the same shape: root object exposes
// `nextEnabled` and `contentItem`, the wizard owns everything else.
//
// SPDX-FileCopyrightText: 2024 Devin Lin <devin@kde.org>
// SPDX-FileCopyrightText: 2025 Kristen McWilliam <kristen@kde.org>
// SPDX-License-Identifier: LGPL-2.0-or-later

#pragma once

#include <QQmlListProperty>
#include <QQuickItem>
#include <qqmlintegration.h>

class SetupModule : public QObject
{
    Q_OBJECT
    QML_ELEMENT

    // Width the module should give its FormCards, pushed down by the wizard so
    // every step lines up at the same measure.
    Q_PROPERTY(qreal cardWidth READ cardWidth WRITE setCardWidth NOTIFY cardWidthChanged)
    // Gate on the wizard's Next button.
    Q_PROPERTY(bool nextEnabled READ nextEnabled WRITE setNextEnabled NOTIFY nextEnabledChanged)
    // Set false to drop the step from the wizard entirely.
    Q_PROPERTY(bool available READ available WRITE setAvailable NOTIFY availableChanged)
    Q_PROPERTY(QQuickItem *contentItem READ contentItem WRITE setContentItem REQUIRED NOTIFY contentItemChanged)
    Q_PROPERTY(QQmlListProperty<QObject> children READ children CONSTANT)
    Q_CLASSINFO("DefaultProperty", "children")

public:
    explicit SetupModule(QObject *parent = nullptr);

    [[nodiscard]] bool available() const;
    void setAvailable(bool available);

    [[nodiscard]] qreal cardWidth() const;
    void setCardWidth(qreal cardWidth);

    [[nodiscard]] QQuickItem *contentItem() const;
    void setContentItem(QQuickItem *contentItem);

    [[nodiscard]] bool nextEnabled() const;
    void setNextEnabled(bool nextEnabled);

    [[nodiscard]] QQmlListProperty<QObject> children();

Q_SIGNALS:
    void availableChanged();
    void contentItemChanged();
    void nextEnabledChanged();
    void cardWidthChanged();
    // The step asks the wizard to advance: for steps whose action lives in
    // the content (Try or Install now, Done, Continue) rather than the
    // wizard's shared Back and Next buttons.
    void advanceRequested();
    // The step asks the wizard to go back to the disk step for another
    // try (the done step after a failure or a cancel).
    void retryRequested();

private:
    bool m_available = true;
    bool m_nextEnabled = true;
    QQuickItem *m_contentItem = nullptr;
    QList<QObject *> m_children;
    qreal m_cardWidth = 0;
};
