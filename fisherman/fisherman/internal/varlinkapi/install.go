package varlinkapi

// PlannedSteps returns the steps an install of plan runs, in order. The
// service and every Executor use it, so the step list a frontend sees is
// the same whatever the backend.
func PlannedSteps(plan InstallPlan) []string {
	var out []string
	for _, s := range StepIDs {
		switch s {
		case StepLUKS:
			if plan.Encryption.Type == "" || plan.Encryption.Type == "none" {
				continue
			}
		case StepTPM2Enroll:
			if plan.Encryption.Type != "tpm2_luks" && plan.Encryption.Type != "tpm2_luks_passphrase" {
				continue
			}
		}
		out = append(out, s)
	}
	return out
}

// stepWeights is each step's share of the whole install, in percent. They
// are estimates that shape the bar, like the weights of the legacy pipeline.
//
// The real executor copies the whole medium root inside the partition step
// (systemd-repart CopyBlocks=, encrypting as it goes): that is where the
// minutes are, 15 GB on an EL10 medium. install_os only checks the copy. The
// weights gave the copy 5 % and the bar sat near 1 % for the whole install
// (installer#515); the copy now has 70 % and reports its own progress.
var stepWeights = map[string]int{
	StepValidateDevice: 1,
	StepPartition:      70,
	StepLUKS:           3,
	StepTPM2Enroll:     2,
	StepMount:          3,
	StepInstallOS:      3,
	StepConfigure:      4,
	StepPostFixups:     5,
	StepBootloader:     4,
	StepFinalize:       5,
	StepCleanup:        0,
}
