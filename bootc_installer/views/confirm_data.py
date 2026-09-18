# confirm_data.py
#
# Copyright 2025 projectbluefin contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundationat version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Data-only module — no GTK imports, safe for pure-Python unit tests."""

_ENC_LABELS = {
    "none": "None",
    "luks-passphrase": "Encrypted with passphrase",
    "tpm2-luks": "Hardware-backed encryption",
    "tpm2-luks-passphrase": "Hardware-backed + passphrase fallback",
}
