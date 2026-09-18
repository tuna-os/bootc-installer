//! Views, built from the cosmic widget set and the cosmic-theme palette.
//!
//! Nothing here hardcodes a colour or a pixel gap: colours come from
//! `cosmic::theme::active().cosmic()` and spacing from its `spacing` scale, so
//! the installer follows the user's COSMIC theme like every other COSMIC app.

use cosmic::iced::{Alignment, Length};
use cosmic::prelude::*;
use cosmic::widget;

use crate::{
    available_encryption_choices, product, Message, Page, TunaInstaller, FILESYSTEMS,
};

/// Every user-facing string of the wizard, in one place.
///
/// The view functions below and [`page_text`] both read from here, so the
/// text the capture harness reports for a page is, by construction, the text
/// that page renders. `{product}` is substituted with [`product::name`].
pub mod copy {
    pub const BACK: &str = "Back";
    pub const CONTINUE: &str = "Continue";

    pub const WELCOME_TITLE: &str = "Install {product}";
    pub const WELCOME_BODY: &str =
        "Welcome. This assistant will guide you through installing {product} onto this computer.";
    pub const WELCOME_CAPTION: &str = "You will choose a target disk and a few options. Nothing is \
         written to any disk until you confirm on the last step.";
    pub const WELCOME_NEXT: &str = "Get started";

    pub const DISK_TITLE: &str = "Select a disk";
    pub const DISK_SUBTITLE: &str = "Everything on the disk you pick will be erased.";
    pub const DISK_SCANNING: &str = "Scanning for disks\u{2026}";
    pub const DISK_UNKNOWN_MODEL: &str = "unknown model";
    pub const DISK_UNKNOWN_BUS: &str = "unknown bus";

    pub const OPTIONS_TITLE: &str = "Options";
    pub const OPTIONS_SUBTITLE: &str =
        "Sensible defaults are already chosen. Change them only if you need to.";
    pub const OPTIONS_SYSTEM: &str = "System";
    pub const OPTIONS_HOSTNAME: &str = "Computer name";
    pub const OPTIONS_FILESYSTEM: &str = "Filesystem";
    pub const OPTIONS_ENCRYPTION: &str = "Encryption";
    pub const OPTIONS_DISK_ENCRYPTION: &str = "Disk encryption";
    pub const OPTIONS_PASSPHRASE: &str = "Passphrase";
    pub const OPTIONS_PASSPHRASE_HINT: &str = "Required to unlock at boot";

    pub const CONFIRM_TITLE: &str = "Confirm";
    pub const CONFIRM_SUBTITLE: &str = "The last screen before anything is written.";
    pub const CONFIRM_SUMMARY: &str = "Summary";
    pub const CONFIRM_TARGET_DISK: &str = "Target disk";
    pub const CONFIRM_IMAGE: &str = "Image";
    pub const CONFIRM_LIVE_SUFFIX: &str = " (this system \u{2014} no download)";
    pub const CONFIRM_WARNING: &str =
        "Everything on the target disk will be erased. This cannot be undone.";
    pub const CONFIRM_INSTALL: &str = "Install";

    pub const INSTALLING_TITLE: &str = "Installing {product}";
    pub const INSTALLING_SUBTITLE: &str = "fisherman is writing the image to disk.";
    pub const INSTALLING_WARNING: &str = "Do not power off the computer.";

    pub const DONE_OK_TITLE: &str = "Installation complete";
    pub const DONE_OK_DETAIL: &str = "Remove the installation media and restart the computer.";
    pub const DONE_FAIL_TITLE: &str = "Installation failed";
    pub const DONE_FAIL_DETAIL: &str = "The install log above has the details.";
    pub const DONE_CLOSE: &str = "Close";
}

use copy::*;

fn with_product(s: &str) -> String {
    s.replace("{product}", &product::name())
}

/// The strings the current page shows, in reading order.
///
/// This is what the capture harness writes to `texts.json` so the shared
/// parity report can match the COSMIC screens against the contract keywords
/// the way the GTK and Qt harnesses do from their widget trees. iced has no
/// widget-tree introspection, so the honest substitute is to render the pages
/// and their text from the same constants.
pub fn page_text(app: &TunaInstaller) -> Vec<String> {
    let recipe = app.recipe();
    match app.page() {
        Page::Welcome => vec![
            with_product(WELCOME_TITLE),
            with_product(WELCOME_BODY),
            WELCOME_CAPTION.to_string(),
            WELCOME_NEXT.to_string(),
        ],
        Page::DiskSelect => {
            let mut t = vec![DISK_TITLE.to_string(), DISK_SUBTITLE.to_string()];
            if app.disks().is_empty() {
                t.push(DISK_SCANNING.to_string());
            }
            for disk in app.disks() {
                t.push(format!("/dev/{}", disk.name));
                t.push(disk_caption(disk));
            }
            t.push(BACK.to_string());
            if app.selected_disk().is_some() {
                t.push(CONTINUE.to_string());
            }
            t
        }
        Page::Options => {
            let choices = available_encryption_choices(app.has_tpm());
            let current = choices
                .iter()
                .find(|c| c.id == recipe.encryption.enc_type);
            let mut t = vec![
                OPTIONS_TITLE.to_string(),
                OPTIONS_SUBTITLE.to_string(),
                OPTIONS_SYSTEM.to_string(),
                OPTIONS_HOSTNAME.to_string(),
                recipe.hostname.clone(),
                OPTIONS_FILESYSTEM.to_string(),
                recipe.filesystem.clone(),
                OPTIONS_ENCRYPTION.to_string(),
                OPTIONS_DISK_ENCRYPTION.to_string(),
            ];
            if let Some(c) = current {
                t.push(c.label.to_string());
                t.push(c.description.to_string());
            }
            if recipe.encryption.enc_type.contains("passphrase") {
                t.push(OPTIONS_PASSPHRASE.to_string());
                t.push(OPTIONS_PASSPHRASE_HINT.to_string());
            }
            t.push(BACK.to_string());
            if app.encryption_ok() {
                t.push(CONTINUE.to_string());
            }
            t
        }
        Page::Confirm => vec![
            CONFIRM_TITLE.to_string(),
            CONFIRM_SUBTITLE.to_string(),
            CONFIRM_WARNING.to_string(),
            CONFIRM_SUMMARY.to_string(),
            CONFIRM_TARGET_DISK.to_string(),
            confirm_disk(app),
            OPTIONS_FILESYSTEM.to_string(),
            recipe.filesystem.clone(),
            OPTIONS_ENCRYPTION.to_string(),
            recipe.encryption.enc_type.clone(),
            OPTIONS_HOSTNAME.to_string(),
            recipe.hostname.clone(),
            CONFIRM_IMAGE.to_string(),
            confirm_image(app),
            BACK.to_string(),
            CONFIRM_INSTALL.to_string(),
        ],
        Page::Installing => vec![
            with_product(INSTALLING_TITLE),
            INSTALLING_SUBTITLE.to_string(),
            app.install_log().to_string(),
            INSTALLING_WARNING.to_string(),
        ],
        Page::Done => {
            let (title, detail) = done_copy(app.install_ok());
            vec![title.to_string(), detail.to_string(), DONE_CLOSE.to_string()]
        }
    }
}

fn disk_caption(disk: &crate::model::DiskInfo) -> String {
    format!(
        "{} \u{b7} {} \u{b7} {}",
        disk.size,
        if disk.model.is_empty() {
            DISK_UNKNOWN_MODEL
        } else {
            &disk.model
        },
        if disk.transport.is_empty() {
            DISK_UNKNOWN_BUS
        } else {
            &disk.transport
        },
    )
}

fn confirm_disk(app: &TunaInstaller) -> String {
    app.selected_disk()
        .and_then(|i| app.disks().get(i))
        .map_or_else(|| "?".to_string(), |d| format!("/dev/{}", d.name))
}

fn confirm_image(app: &TunaInstaller) -> String {
    match (app.live_image(), app.recipe().image.is_empty()) {
        (Some(live), true) => format!("{live}{CONFIRM_LIVE_SUFFIX}"),
        _ => app.recipe().image.clone(),
    }
}

fn done_copy(ok: bool) -> (&'static str, &'static str) {
    if ok {
        (DONE_OK_TITLE, DONE_OK_DETAIL)
    } else {
        (DONE_FAIL_TITLE, DONE_FAIL_DETAIL)
    }
}

pub fn view(app: &TunaInstaller) -> Element<'_, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    // Deliberately renders nothing, so the capture harness's pixel gate can be
    // calibrated against a measured blank frame instead of a guessed one. This
    // is how the numbers in `capture.rs` were derived at the broken end, and
    // re-running it is how they should be re-derived if the UI changes:
    //
    //     TUNA_BLANK_SELFTEST=1 TUNA_CAPTURE_DIR=/tmp/blank just capture
    //
    // It must FAIL. If it ever passes, the gate has stopped detecting a page
    // that did not render, which is the entire point of the gate.
    if std::env::var_os("TUNA_BLANK_SELFTEST").is_some() {
        return widget::container(widget::space::horizontal())
            .width(Length::Fill)
            .height(Length::Fill)
            .into();
    }
    let content: Element<Message> = match app.page() {
        Page::Welcome => welcome(app),
        Page::DiskSelect => disk_select(app),
        Page::Options => options(app),
        Page::Confirm => confirm(app),
        Page::Installing => installing(app),
        Page::Done => done(app),
    };

    widget::container(content)
        .width(Length::Fill)
        .height(Length::Fill)
        .padding(spacing.space_l)
        .into()
}

/// Back / spacer / forward, the shape every COSMIC wizard uses.
fn nav_row<'a>(
    back: Option<Message>,
    forward: Option<(&'a str, Message, bool)>,
) -> Element<'a, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;
    let mut row = widget::row::with_capacity(3).spacing(spacing.space_s);

    if let Some(msg) = back {
        row = row.push(widget::button::standard(BACK).on_press(msg));
    }
    row = row.push(widget::space::horizontal());
    if let Some((label, msg, destructive)) = forward {
        let button = if destructive {
            widget::button::destructive(label)
        } else {
            widget::button::suggested(label)
        };
        row = row.push(button.on_press(msg));
    }
    row.align_y(Alignment::Center).into()
}

fn welcome(_app: &TunaInstaller) -> Element<'_, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let hero = widget::column::with_children(vec![
        widget::icon::from_name("drive-harddisk-symbolic")
            .size(64)
            .icon()
            .into(),
        widget::text::title1(with_product(WELCOME_TITLE)).into(),
        widget::text::body(with_product(WELCOME_BODY)).into(),
        widget::text::caption(WELCOME_CAPTION).into(),
    ])
    .spacing(spacing.space_s)
    .align_x(Alignment::Center)
    .width(Length::Fill);

    widget::column::with_children(vec![
        widget::space::vertical().into(),
        hero.into(),
        widget::space::vertical().into(),
        nav_row(None, Some((WELCOME_NEXT, Message::NextPage, false))),
    ])
    .spacing(spacing.space_m)
    .height(Length::Fill)
    .into()
}

fn disk_select(app: &TunaInstaller) -> Element<'_, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let body: Element<Message> = if app.disks().is_empty() {
        widget::column::with_children(vec![
            widget::progress_bar::indeterminate_linear()
                .width(Length::Fill)
                .into(),
            widget::text::body(DISK_SCANNING).into(),
        ])
        .spacing(spacing.space_s)
        .into()
    } else {
        let mut list = widget::list_column().style(cosmic::theme::Container::List);
        for (i, disk) in app.disks().iter().enumerate() {
            let _selected = app.selected_disk() == Some(i);

            let label = widget::column::with_children(vec![
                widget::text::body(format!("/dev/{}", disk.name)).into(),
                widget::text::caption(disk_caption(disk)).into(),
            ])
            .spacing(spacing.space_xxxs)
            .width(Length::Fill);

            let row = widget::row::with_children(vec![
                label.into(),
                widget::radio(widget::text::body(""), i, app.selected_disk(), Message::SelectDisk)
                    .into(),
            ])
            .align_y(Alignment::Center)
            .spacing(spacing.space_s);

            list = list.add(
                widget::mouse_area(row)
                    .on_press(Message::SelectDisk(i)),
            );
        }
        widget::scrollable(list.into_element())
            .height(Length::Fill)
            .into()
    };

    page_frame(
        DISK_TITLE,
        DISK_SUBTITLE,
        body,
        nav_row(
            Some(Message::BackPage),
            app.selected_disk()
                .map(|_| (CONTINUE, Message::NextPage, false)),
        ),
    )
}

fn options(app: &TunaInstaller) -> Element<'_, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;
    let recipe = app.recipe();

    let fs_index = FILESYSTEMS.iter().position(|f| *f == recipe.filesystem);

    // tunaOS#734: this list is `has_tpm`-filtered, same set XFCE offers on
    // this hardware, and `idx` below is a position in it — NOT in the full
    // `ENCRYPTION_CHOICES` table. `update()`'s `EncryptionChanged` handler
    // rebuilds the identical filtered list before indexing into it, so the
    // two stay in lockstep without passing the list through a message.
    let enc_choices = available_encryption_choices(app.has_tpm());
    let enc_index = enc_choices
        .iter()
        .position(|c| c.id == recipe.encryption.enc_type);
    let enc_labels: Vec<&str> = enc_choices.iter().map(|c| c.label).collect();
    let enc_description = enc_index
        .and_then(|i| enc_choices.get(i))
        .map(|c| c.description)
        .unwrap_or_default();
    // "luks-passphrase" and "tpm2-luks-passphrase" both contain this
    // substring; bare "tpm2-luks" and "none" don't. Same test `encryption_ok()`
    // uses to gate Continue below, so the field's presence and the field's
    // requiredness can never disagree.
    let needs_passphrase = recipe.encryption.enc_type.contains("passphrase");

    let system = widget::settings::section()
        .title(OPTIONS_SYSTEM)
        .add(widget::settings::item(
            OPTIONS_HOSTNAME,
            widget::text_input("tunaos", &recipe.hostname)
                .on_input(Message::HostnameChanged)
                .width(Length::Fixed(260.0)),
        ))
        .add(widget::settings::item(
            OPTIONS_FILESYSTEM,
            widget::dropdown(&FILESYSTEMS, fs_index, Message::FilesystemChanged),
        ));

    let mut security = widget::settings::section().title(OPTIONS_ENCRYPTION).add(
        widget::settings::item::builder(OPTIONS_DISK_ENCRYPTION)
            .description(enc_description)
            // Handed over by value, not as `.as_slice()`: the returned
            // `Element` outlives this function, so a borrow of the local
            // `Vec` would not compile (E0515). `Vec<&'static str>` converts
            // into an owned `Cow<[&str]>`, which the dropdown keeps.
            .control(widget::dropdown(
                enc_labels,
                enc_index,
                Message::EncryptionChanged,
            )),
    );

    // Only build the passphrase controls once the chosen encryption actually
    // carries one. The KDE sibling crashed precisely at this kind of
    // conditional: its constructor called setChecked() before the passphrase
    // widgets existed, so the toggled handler ran against uninitialised
    // pointers. In Rust the equivalent mistake cannot compile, but the
    // conditional is still the honest UI — and "tpm2-luks" alone must NOT show
    // this field, since fisherman never reads a passphrase for it.
    if needs_passphrase {
        security = security.add(widget::settings::item(
            OPTIONS_PASSPHRASE,
            widget::secure_input(
                OPTIONS_PASSPHRASE_HINT,
                &recipe.encryption.passphrase,
                Some(Message::TogglePassphraseVisible),
                app.passphrase_hidden(),
            )
            .on_input(Message::PassphraseChanged)
            .width(Length::Fixed(260.0)),
        ));
    }

    let body = widget::scrollable(
        widget::settings::view_column(vec![system.into(), security.into()])
            .spacing(spacing.space_m),
    )
    .height(Length::Fill);

    page_frame(
        OPTIONS_TITLE,
        OPTIONS_SUBTITLE,
        body.into(),
        nav_row(
            Some(Message::BackPage),
            // Blocked while a passphrase-carrying choice has an empty
            // passphrase, so this can never reach Confirm/Install and only
            // then discover fisherman rejects the recipe (tunaOS#734).
            app.encryption_ok()
                .then_some((CONTINUE, Message::NextPage, false)),
        ),
    )
}

fn confirm(app: &TunaInstaller) -> Element<'_, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;
    let recipe = app.recipe();

    let disk = confirm_disk(app);
    let image = confirm_image(app);

    let summary = widget::settings::section()
        .title(CONFIRM_SUMMARY)
        .add(widget::settings::item(CONFIRM_TARGET_DISK, widget::text::body(disk)))
        .add(widget::settings::item(
            OPTIONS_FILESYSTEM,
            widget::text::body(recipe.filesystem.clone()),
        ))
        .add(widget::settings::item(
            OPTIONS_ENCRYPTION,
            widget::text::body(recipe.encryption.enc_type.clone()),
        ))
        .add(widget::settings::item(
            OPTIONS_HOSTNAME,
            widget::text::body(recipe.hostname.clone()),
        ))
        .add(widget::settings::item(CONFIRM_IMAGE, widget::text::body(image)));

    // Not `widget::warning::warning`: its filled amber background renders the
    // body text near-invisible on the dark COSMIC palette, which the first
    // screenshot run made obvious and no diff ever would have. A card with
    // warning-coloured text keeps the emphasis and stays legible in both
    // light and dark.
    let theme = cosmic::theme::active();
    let warning = widget::container(
        widget::row::with_children(vec![
            widget::icon::from_name("dialog-warning-symbolic")
                .size(16)
                .icon()
                .into(),
            widget::text::body(CONFIRM_WARNING)
            .class(cosmic::theme::Text::Color(
                theme.cosmic().warning_text_color().into(),
            ))
            .into(),
        ])
        .spacing(spacing.space_xs)
        .align_y(Alignment::Center),
    )
    .class(cosmic::theme::Container::Card)
    .padding(spacing.space_s)
    .width(Length::Fill);

    let body = widget::scrollable(
        widget::column::with_children(vec![warning.into(), summary.into()])
            .spacing(spacing.space_m),
    )
    .height(Length::Fill);

    page_frame(
        CONFIRM_TITLE,
        CONFIRM_SUBTITLE,
        body.into(),
        nav_row(
            Some(Message::BackPage),
            Some((CONFIRM_INSTALL, Message::StartInstall, true)),
        ),
    )
}

fn installing(app: &TunaInstaller) -> Element<'_, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;
    let theme = cosmic::theme::active();
    let cosmic_theme = theme.cosmic();

    let log = widget::container(
        widget::scrollable(
            widget::text::monotext(app.install_log())
                .size(12)
                .width(Length::Fill),
        )
        .height(Length::Fill),
    )
    .class(cosmic::theme::Container::Card)
    .padding(spacing.space_s)
    .width(Length::Fill)
    .height(Length::Fill);

    let body = widget::column::with_children(vec![
        widget::progress_bar::indeterminate_linear()
            .width(Length::Fill)
            .into(),
        log.into(),
        widget::text::caption(INSTALLING_WARNING)
            .class(cosmic::theme::Text::Color(cosmic_theme.warning_text_color().into()))
            .into(),
    ])
    .spacing(spacing.space_s)
    .height(Length::Fill);

    page_frame(
        with_product(INSTALLING_TITLE),
        INSTALLING_SUBTITLE,
        body.into(),
        widget::space::horizontal().into(),
    )
}

fn done(app: &TunaInstaller) -> Element<'_, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;
    let theme = cosmic::theme::active();
    let cosmic_theme = theme.cosmic();

    let (title, detail) = done_copy(app.install_ok());
    let (icon, colour) = if app.install_ok() {
        ("emblem-ok-symbolic", cosmic_theme.success_text_color())
    } else {
        ("dialog-error-symbolic", cosmic_theme.destructive_text_color())
    };

    let hero = widget::column::with_children(vec![
        widget::icon::from_name(icon).size(64).icon().into(),
        widget::text::title2(title)
            .class(cosmic::theme::Text::Color(colour.into()))
            .into(),
        widget::text::body(detail).into(),
    ])
    .spacing(spacing.space_s)
    .align_x(Alignment::Center)
    .width(Length::Fill);

    widget::column::with_children(vec![
        widget::space::vertical().into(),
        hero.into(),
        widget::space::vertical().into(),
        nav_row(None, Some((DONE_CLOSE, Message::Quit, false))),
    ])
    .spacing(spacing.space_m)
    .height(Length::Fill)
    .into()
}

/// Title, subtitle, scrolling body, navigation footer.
fn page_frame<'a>(
    title: impl Into<std::borrow::Cow<'a, str>> + 'a,
    subtitle: impl Into<std::borrow::Cow<'a, str>> + 'a,
    body: Element<'a, Message>,
    footer: Element<'a, Message>,
) -> Element<'a, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;
    widget::column::with_children(vec![
        widget::text::title2(title).into(),
        widget::text::caption(subtitle).into(),
        widget::divider::horizontal::default().into(),
        body,
        widget::divider::horizontal::default().into(),
        footer,
    ])
    .spacing(spacing.space_s)
    .height(Length::Fill)
    .into()
}
