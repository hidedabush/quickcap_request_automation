(function () {
  "use strict";

  function byId(id) { return document.getElementById(id); }

  function toggleApprovedSection() {
    var statusSelect = byId("status_select");
    var section = byId("approved-section");
    if (!statusSelect || !section) return;
    var isApproved = statusSelect.value === "Approved";
    section.style.display = isApproved ? "block" : "none";

    if (isApproved) {
      var nameField = byId("name_field");
      var orgName = byId("organization_name");
      if (nameField && !nameField.value && orgName) {
        nameField.value = orgName.value;
      }
    }
  }

  function openPopup(url) {
    window.open(url, "quickcapPopup", "width=980,height=640,resizable=yes,scrollbars=yes");
  }

  function wireOrgSearch() {
    var btn = byId("orgSearchBtn");
    if (!btn) return;
    btn.addEventListener("click", function () {
      var token = window.QC_TOKEN || "";
      openPopup("/popup/organizations?token=" + encodeURIComponent(token));
    });
  }

  function wireGroupSearch() {
    var btn = byId("groupSearchBtn");
    if (!btn) return;
    btn.addEventListener("click", function () {
      var token = window.QC_TOKEN || "";
      openPopup("/popup/groups?token=" + encodeURIComponent(token));
    });
  }

  function wireSendEmailStub() {
    var btn = byId("sendEmailBtn");
    if (!btn) return;
    btn.addEventListener("click", function () {
      btn.textContent = "Email Sent (local, not really sent)";
      btn.disabled = true;
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var statusSelect = byId("status_select");
    if (statusSelect) {
      statusSelect.addEventListener("change", toggleApprovedSection);
      toggleApprovedSection();
    }
    wireOrgSearch();
    wireGroupSearch();
    wireSendEmailStub();
  });
})();