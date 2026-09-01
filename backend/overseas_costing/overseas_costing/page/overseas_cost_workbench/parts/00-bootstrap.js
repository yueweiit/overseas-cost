frappe.pages["overseas-cost-workbench"] = frappe.pages["overseas-cost-workbench"] || {};

function hideDeskChromeWhenReady(workbench) {
  workbench.hideDeskChrome();
  requestAnimationFrame(() => workbench.hideDeskChrome());
  window.setTimeout(() => {
    if ($(workbench.wrapper).is(":visible")) workbench.hideDeskChrome();
  }, 300);
}

function ensureDeskModuleSidebar(workbench) {
  const $nativeSidebar = $(
    ".body-sidebar-container, .desk-sidebar-container, .app-sidebar, .standard-sidebar"
  ).first();
  if ($nativeSidebar.length) {
    $nativeSidebar.css({ display: "", visibility: "visible", opacity: "1" });
    $("#ocw-erp-module-sidebar-fallback").remove();
    $("body").removeClass("ocw-has-erp-module-sidebar-fallback");
    return;
  }

  const fallbackHosts = new Set(["127.0.0.1", "localhost", "development.localhost"]);
  if (!fallbackHosts.has(window.location.hostname)) {
    $("#ocw-erp-module-sidebar-fallback").remove();
    $("body").removeClass("ocw-has-erp-module-sidebar-fallback");
    return;
  }

  if ($("#ocw-erp-module-sidebar-fallback").length) return;

  const modules = [
    { label: "组织", href: "/app/users", icon: "users" },
    { label: "会计", href: "/app/accounting", icon: "book-open" },
    { label: "资产", href: "/app/assets", icon: "asset" },
    { label: "采购", href: "/app/buying", icon: "shopping-cart" },
    { label: "生产", href: "/app/manufacturing", icon: "production" },
    { label: "项目", href: "/app/projects", icon: "folder" },
    { label: "质量", href: "/app/quality", icon: "check-circle" },
    { label: "销售", href: "/app/selling", icon: "sell" },
    { label: "库存", href: "/app/stock", icon: "stock" },
    { label: "委外", href: "/app/subcontracting-order", icon: "tool" },
    { label: "设置", href: "/app/system-settings", icon: "setting" },
    {
      label: "海外成本核算",
      href: "/app/overseas-cost-workbench",
      icon: "calculator",
      active: true,
    },
  ];
  const renderIcon = (name) =>
    frappe.utils && frappe.utils.icon
      ? frappe.utils.icon(name, "md")
      : `<span class="ocw-erp-module-icon-fallback">${name.slice(0, 1).toUpperCase()}</span>`;
  const $sidebar = $(
    `<aside id="ocw-erp-module-sidebar-fallback" aria-label="ERP 模块导航">
      <div class="ocw-erp-module-sidebar-items">
        ${modules
          .map(
            (item) => `
              <a class="ocw-erp-module-link${item.active ? " is-active" : ""}"
                 href="${item.href}" title="${item.label}" aria-label="${item.label}">
                <span class="ocw-erp-module-icon">${renderIcon(item.icon)}</span>
                <span class="ocw-erp-module-label">${item.label}</span>
              </a>
            `
          )
          .join("")}
      </div>
    </aside>`
  );
  $("body").append($sidebar).addClass("ocw-has-erp-module-sidebar-fallback");
  workbench.applyDeskLayout();
}

frappe.pages["overseas-cost-workbench"].on_page_load = function (wrapper) {
  const workbench = new OverseasCostWorkbench(wrapper);
  frappe.pages["overseas-cost-workbench"].workbench = workbench;
  workbench.init();
  ensureDeskModuleSidebar(workbench);
  hideDeskChromeWhenReady(workbench);
  // 离开工作台时恢复桌面外壳（侧栏 / 顶部标签栏 / 右侧栏），避免影响其它页面。
  $(wrapper).on("hide", function () {
    workbench.restoreDeskChrome();
  });
};

frappe.pages["overseas-cost-workbench"].on_page_show = function () {
  const workbench = frappe.pages["overseas-cost-workbench"].workbench;
  if (!workbench) return;
  ensureDeskModuleSidebar(workbench);
  hideDeskChromeWhenReady(workbench);
  workbench.applyDeskLayout();
  requestAnimationFrame(() => workbench.applyDeskLayout());
};

