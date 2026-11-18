const packageSelect = document.querySelector("#package");
const depositSummary = document.querySelector("#deposit");
const intakeGroups = document.querySelectorAll("[data-intake-group]");

if (packageSelect) {
  function showPackageDetails() {
    const option = packageSelect.selectedOptions[0];
    const deposit = option?.dataset.deposit;
    depositSummary.textContent = deposit
      ? `Total: ${option.dataset.total} · 50% deposit: ${deposit} · Balance on delivery: ${deposit}`
      : "";

    for (const group of intakeGroups) {
      const active = group.dataset.intakeGroup === option?.dataset.intake;
      group.hidden = !active;
      group.disabled = !active;
    }
  }

  packageSelect.addEventListener("change", showPackageDetails);
  showPackageDetails();
}
