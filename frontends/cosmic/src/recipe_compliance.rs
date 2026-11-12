//! The cross-frontend recipe contract: the COSMIC half (#226, #186).
//!
//! `shared/recipe/fixtures/compliance.json` holds one set of choices per
//! case and the one recipe that every frontend must write for it. This test
//! makes the choices with the code that the update loop runs for each
//! page: the branding at init, `Recipe::apply_leaf` for the selected leaf
//! of the shared catalog fixture, the disk, `choose_filesystem`,
//! `choose_encryption`, the hostname, `user_block` with the account groups,
//! the region picks, and `for_fisherman` (what `install_recipe` sends). The
//! recipe is normalised with the fixture's table and its bytes must be the
//! expected recipe's (`shared/recipe/compliance.py` is the reference).

use crate::{branding, image_catalog, model, model::Recipe};
use serde_json::{Map, Value};

const FIXTURE: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../shared/recipe/fixtures/compliance.json"
);

fn read(path: &str) -> String {
    std::fs::read_to_string(path).unwrap_or_else(|e| panic!("{path}: {e}"))
}

fn fixture() -> Value {
    serde_json::from_str(&read(FIXTURE)).expect("compliance.json is JSON")
}

/// The object that holds the last key of `path`.
fn parent<'a>(recipe: &'a mut Value, path: &[Value]) -> Option<&'a mut Map<String, Value>> {
    let mut node = recipe;
    for key in &path[..path.len() - 1] {
        node = node.get_mut(key.as_str()?)?;
    }
    node.as_object_mut()
}

/// The fixture's two rules: a key whose value is the listed one is absent,
/// and so is an object without its `needs` key.
fn normalise(table: &Value, mut recipe: Value) -> Value {
    for rule in table["absent_equals"].as_array().expect("absent_equals") {
        let path = rule["key"].as_array().expect("key");
        let last = path.last().and_then(Value::as_str).expect("key");
        if let Some(object) = parent(&mut recipe, path) {
            if object.get(last) == Some(&rule["value"]) {
                object.remove(last);
            }
        }
    }
    for rule in table["absent_without"].as_array().expect("absent_without") {
        let path = rule["key"].as_array().expect("key");
        let last = path.last().and_then(Value::as_str).expect("key");
        let needs = rule["needs"].as_str().expect("needs");
        if let Some(object) = parent(&mut recipe, path) {
            if object
                .get(last)
                .and_then(Value::as_object)
                .is_some_and(|o| !o.contains_key(needs))
            {
                object.remove(last);
            }
        }
    }
    recipe
}

/// Keys sorted at every depth, no spaces: the bytes the frontends compare.
/// Sorted here, because a dependency can turn on serde_json's
/// `preserve_order`.
fn canonical(value: &Value) -> String {
    match value {
        Value::Object(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            let fields: Vec<String> = keys
                .into_iter()
                .map(|k| format!("{}:{}", Value::String(k.clone()), canonical(&map[k])))
                .collect();
            format!("{{{}}}", fields.join(","))
        }
        Value::Array(items) => format!(
            "[{}]",
            items.iter().map(canonical).collect::<Vec<_>>().join(",")
        ),
        other => other.to_string(),
    }
}

fn str_of<'a>(value: &'a Value, key: &str) -> &'a str {
    value[key].as_str().unwrap_or_default()
}

/// The recipe that the wizard sends for the case's choices.
fn cosmic_recipe(fx: &Value, choices: &Value) -> Value {
    let catalog_path = format!(
        "{}/../../{}",
        env!("CARGO_MANIFEST_DIR"),
        fx["catalog"].as_str().expect("catalog")
    );
    let catalog =
        image_catalog::parse_manifest(&read(&catalog_path)).expect("the catalog fixture parses");
    let leaf = catalog
        .find(str_of(choices, "image"))
        .map(|i| &catalog.leaves[i])
        .expect("the catalog has the leaf");
    let machine = &choices["machine"];
    let machine = model::Machine {
        has_nvidia: machine["has_nvidia"].as_bool().unwrap(),
        is_live: machine["is_live"].as_bool().unwrap(),
        offline_images: machine["offline_images"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(|v| v.as_str().map(str::to_string))
            .collect(),
    };

    // init(): the branding contract fills the identity.
    let file = fx["branding"].as_object().expect("branding");
    let brand = branding::from_sources(Some(file), None, "");
    let mut recipe = Recipe::default();
    recipe.distro_id = brand.id.clone();
    recipe.hostname = brand.default_hostname.clone();

    // The image page: the leaf, then the disk page.
    recipe.apply_leaf(leaf, &machine);
    recipe.disk = str_of(choices, "disk").to_string();
    let filesystem = str_of(choices, "filesystem");
    assert!(
        leaf.filesystem_choices().iter().any(|f| f == filesystem),
        "the disk page does not offer {filesystem}"
    );
    recipe.choose_filesystem(filesystem);
    recipe.hostname = str_of(choices, "hostname").to_string();

    // The encryption page.
    let encryption = &choices["encryption"];
    recipe.choose_encryption(str_of(encryption, "type"));
    if crate::validate::needs_passphrase(str_of(encryption, "type")) {
        recipe.encryption.passphrase = str_of(encryption, "passphrase").to_string();
    }

    // The account page, which the wizard shows only when the image needs
    // an account (`account_required_for`).
    if super::account_required_for(&catalog, None, "", Some(leaf)) {
        if let Some(account) = choices["account"].as_object() {
            let text = |key: &str| account.get(key).and_then(Value::as_str).unwrap_or_default();
            recipe.user = model::user_block(
                text("username"),
                text("fullname"),
                text("password"),
                &model::groups_for(None),
            );
        }
    }

    // The language, keyboard and time zone pages.
    let locale = str_of(choices, "locale");
    if !locale.is_empty() {
        recipe.locale = locale.to_string();
    }
    if let Some(layout) = choices["keyboard"].get("layout").and_then(Value::as_str) {
        assert_eq!(
            choices["keyboard"].as_object().map(Map::len),
            Some(1),
            "the keyboard page offers layouts only"
        );
        recipe.choose_keyboard(layout);
    }
    let timezone = str_of(choices, "timezone");
    if !timezone.is_empty() {
        recipe.timezone = timezone.to_string();
    }
    recipe.for_fisherman()
}

#[test]
fn cosmic_writes_the_expected_recipe() {
    let fx = fixture();
    let cases = fx["cases"].as_array().expect("cases");
    assert!(
        cases.len() >= 2,
        "compliance.json is smaller than this test understands"
    );
    for case in cases {
        let got = canonical(&normalise(
            &fx["normalise"],
            cosmic_recipe(&fx, &case["choices"]),
        ));
        let want = canonical(&normalise(&fx["normalise"], case["recipe"].clone()));
        assert_eq!(
            got, want,
            "{}: the recipe differs from shared/recipe/fixtures/compliance.json",
            case["name"]
        );
    }
}

#[test]
fn the_normaliser_is_the_fixtures() {
    let fx = fixture();
    let recipe = serde_json::json!({
        "disk": "/dev/vda", "composeFsBackend": false, "imageType": "bootc", "bootloader": "",
        "selinuxDisabled": false, "btrfsSubvolumes": false,
        "encryption": {"type": "none", "passphrase": ""},
        "user": {"username": "", "fullname": "", "password": "", "groups": []},
    });
    assert_eq!(
        canonical(&normalise(&fx["normalise"], recipe)),
        r#"{"disk":"/dev/vda","encryption":{"type":"none"}}"#
    );
    // A value that is not the default stays, and so does one of another type.
    let kept = serde_json::json!({"composeFsBackend": true, "btrfsSubvolumes": 0, "bootloader": "grub2",
        "user": {"username": "jo"}});
    assert_eq!(
        canonical(&normalise(&fx["normalise"], kept)),
        r#"{"bootloader":"grub2","btrfsSubvolumes":0,"composeFsBackend":true,"user":{"username":"jo"}}"#
    );
}
