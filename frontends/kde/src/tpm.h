#pragma once

#include <QString>

// TPM 2.0 detection, per shared/tpm/README.md.
namespace tpm {

// The kernel writes the TCG spec major version here: "2" for TPM 2.0, "1"
// for TPM 1.2. Added in Linux 5.5.
inline constexpr const char *VERSION_FILE = "sys/class/tpm/tpm0/tpm_version_major";

// The in-kernel resource manager is a TPM 2.0 feature, so the kernel makes
// this node only for a 2.0 device. Fallback for kernels older than 5.5.
inline constexpr const char *RESOURCE_MANAGER = "dev/tpmrm0";

// Whether `root` holds a TPM 2.0 device.
//
// This used to test /sys/class/tpm/tpm0 for existence, which the kernel also
// creates for a TPM 1.2 device -- so a 1.2 machine was offered tpm2-luks and
// the install failed at enrolment, after the disk had been partitioned. The
// root parameter is what makes this testable: no CI runner has a TPM of any
// version, so the tests point it at a fixture tree.
bool probe2(const QString &root);

}
