"""Tour carousel (tour.py): slides from the catalog, pager behavior."""

import os
import sys
import types

import gi

gi.require_version("Gtk", "3.0")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tuna_installer_xfce import tour  # noqa: E402


def _root(name, desc="", subtitle=""):
    return types.SimpleNamespace(name=name, desc=desc, subtitle=subtitle)


def test_slides_come_from_catalog_roots_in_order():
    catalog = [_root("Workstation", "Daily driver."),
               _root("Server", "", "Headless."),
               _root("", "Nameless has no slide."),
               _root("Empty")]
    slides = tour.slides_from_catalog(catalog)
    assert slides == [{"title": "Workstation", "description": "Daily driver."},
                      {"title": "Server", "description": "Headless."}]


def test_no_catalog_means_no_slides():
    assert tour.slides_from_catalog([]) == []
    assert tour.slides_from_catalog(None) == []


def test_carousel_hides_without_slides():
    box = tour.TourCarousel()
    box.set_slides([])
    assert not box.get_visible()
    assert len(box) == 0


def test_carousel_pages_and_clamps():
    box = tour.TourCarousel()
    box.set_slides([{"title": "A", "description": "a"},
                    {"title": "B", "description": "b"}])
    assert len(box) == 2
    assert box.get_visible()
    box.show(5)
    assert box.position.get_text() == "2 of 2"
    assert not box.next_btn.get_sensitive()
    box.show(0)
    assert box.position.get_text() == "1 of 2"
    assert not box.prev_btn.get_sensitive()


def test_welcome_page_carries_the_tour(monkeypatch):
    from tuna_installer_xfce import core, pages
    monkeypatch.setattr(core, "load_catalog", lambda: core.Catalog(
        {"images": [{"name": "Workstation", "desc": "Daily driver.", "children": []}]}))
    welcome = pages.WelcomePage(None)
    assert len(welcome.tour) == 1
