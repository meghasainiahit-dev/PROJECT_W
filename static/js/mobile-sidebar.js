(function () {
  const mobileQuery = window.matchMedia("(max-width: 899px)");

  function findSidebar() {
    return document.querySelector(".sidebar, .side, .desktop-sidebar");
  }

  function closeSidebar() {
    document.body.classList.remove("mobile-sidebar-open");
    const toggle = document.querySelector(".mobile-menu-toggle");
    if (toggle) {
      toggle.setAttribute("aria-expanded", "false");
      toggle.innerHTML = '<i class="bi bi-list"></i>';
    }
  }

  function openSidebar() {
    document.body.classList.add("mobile-sidebar-open");
    const toggle = document.querySelector(".mobile-menu-toggle");
    if (toggle) {
      toggle.setAttribute("aria-expanded", "true");
      toggle.innerHTML = '<i class="bi bi-x-lg"></i>';
    }
  }

  function setupMobileSidebar() {
    const sidebar = findSidebar();
    if (!sidebar || document.querySelector(".mobile-menu-toggle")) return;

    sidebar.setAttribute("id", sidebar.id || "mobileSidebar");

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "mobile-menu-toggle";
    toggle.setAttribute("aria-label", "Open navigation");
    toggle.setAttribute("aria-controls", sidebar.id);
    toggle.setAttribute("aria-expanded", "false");
    toggle.innerHTML = '<i class="bi bi-list"></i>';

    const backdrop = document.createElement("button");
    backdrop.type = "button";
    backdrop.className = "mobile-sidebar-backdrop";
    backdrop.setAttribute("aria-label", "Close navigation");

    document.body.prepend(backdrop);
    document.body.prepend(toggle);

    toggle.addEventListener("click", () => {
      if (document.body.classList.contains("mobile-sidebar-open")) {
        closeSidebar();
      } else {
        openSidebar();
      }
    });

    backdrop.addEventListener("click", closeSidebar);

    sidebar.addEventListener("click", (event) => {
      const link = event.target.closest("a");
      if (link && mobileQuery.matches) closeSidebar();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeSidebar();
    });

    mobileQuery.addEventListener("change", (event) => {
      if (!event.matches) closeSidebar();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setupMobileSidebar);
  } else {
    setupMobileSidebar();
  }
})();
