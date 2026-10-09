# TPM2 detection contract

The `tpm2-luks` encryption modes need a TPM 2.0 device. This file says how
to decide whether to offer them. fisherman makes that decision for every
frontend (see "Implementation").

## The probe

Read `/sys/class/tpm/tpm0/tpm_version_major`. The kernel ABI
(`Documentation/ABI/stable/sysfs-class-tpm`) defines it:

> The "tpm_version_major" property shows the TCG spec major version
> implemented by the TPM device.

A TPM 2.0 device reads `2`. A TPM 1.2 device reads `1`.

If the file is absent, look for `/dev/tpmrm0`. The kernel makes that device
node only for TPM 2.0, because the in-kernel resource manager is a TPM 2.0
feature. This covers kernels before 5.5, which is when `tpm_version_major`
was added.

If neither is present, there is no TPM 2.0.

## What was wrong before

Every frontend tested `/sys/class/tpm/tpm0` for existence. The kernel makes
that directory for a TPM 1.2 device too. A TPM 1.2 machine was therefore
offered `tpm2-luks`, and the install failed at enrolment, after fisherman
had already partitioned the disk.

## Rules

- Do not test `/sys/class/tpm/tpm0` for existence. It is true for TPM 1.2.
- Read the version file. Accept only `2`.
- Take a root directory parameter. The tests give it a fixture directory,
  which is the only way to exercise this on a runner with no TPM.
- `BOOTC_INSTALLER_FAKE_TPM` forces the answer to true, and never to false.
  It makes the choices visible for a screenshot. It does not make them work.

## Fixtures

`fixtures/` holds one directory tree per case. fisherman's probe tests use
copies of these trees and must agree:

| tree | holds | result |
|---|---|---|
| `tpm2/` | `tpm_version_major` = `2` | true |
| `tpm12/` | `tpm_version_major` = `1` | false |
| `legacy-tpm2/` | no version file, `dev/tpmrm0` | true |
| `legacy-none/` | no version file, no `dev/tpmrm0` | false |

## Implementation

fisherman applies this contract one time: `fisherman probe --json` reports
it as `tpm.usable` (`fisherman/docs/PROBE.md`). Its tests use copies of
`fixtures/`, and `tests/unit/test_shared_tpm.py` checks that those copies
match these trees.

No frontend probes the TPM itself. Each one reads `tpm.usable` through its
probe reader (`shared/probe/README.md`). The same test fails if a frontend
source reads `tpm_version_major`, `/dev/tpmrm0` or `/sys/class/tpm` again.

`BOOTC_INSTALLER_FAKE_TPM` is read by fisherman, not by the frontends. A
capture harness can also point `BOOTC_INSTALLER_FAKE_PROBE` at a probe
fixture whose `tpm.usable` is true.
