// A FormCard password field with an accessible name.
//
// The delegate of Kirigami Addons shows its label above the field and gives
// the field no name. Qt then takes the text of the field as its name, and a
// screen reader reads the password (tuna-os/tunaOS run 45647965089).
//
// SPDX-License-Identifier: GPL-3.0-only

import QtQuick

import org.kde.kirigamiaddons.formcard as FormCard

FormCard.FormPasswordFieldDelegate {
    id: delegate

    function nameField(item: Item): void {
        for (const child of item.children) {
            if (child instanceof TextInput) {
                child.Accessible.name = delegate.label;
            } else {
                nameField(child);
            }
        }
    }

    Component.onCompleted: nameField(delegate)
}
