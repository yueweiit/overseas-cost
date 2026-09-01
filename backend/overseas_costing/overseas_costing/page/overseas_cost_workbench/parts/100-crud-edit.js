  async setAllExpanded(expanded) {
    const displayBatches = this.getDisplayedBatches();
    if (expanded) {
      await this.prefetchBatchItems(displayBatches);
      this.expandedBatchNames = new Set(displayBatches.map((batch) => batch.name));
      this.addAudit("人工", "manual", "全部展开");
    } else {
      this.expandedBatchNames.clear();
      this.addAudit("系统", "system", "全部收起");
    }
    this.renderTable();
  }

  confirmDeleteBatch(batchName) {
    const batch = this.findBatch(batchName);
    if (!batch) return;
    const items = this.batchItems[batch.name] || [];
    const label = `${batch.customs_no || "--"} / ${batch.waybill_no || batch.batch_no || batch.name}`;
    frappe.confirm(
      `
        <div class="ocw-confirm-copy">
          <h4>确认删除报关/运单块？</h4>
          <p>将删除 ${this.escape(label)}，同时移除其下 ${items.length || batch.item_count || 0} 条物料明细。</p>
          <div class="ocw-confirm-note">删除后会同时清理该批次的版本、分摊规则、附件记录和修改记录。请仅删除测试或误导入数据。</div>
        </div>
      `,
      async () => {
        await this.deleteBatch(batch, label);
      }
    );
  }

  async deleteBatch(batch, label) {
    try {
      const result = await this.call(
        "overseas_costing.api.calculate.delete_batch",
        {
          batch_name: batch.name,
          remark: `前端删除批次：${label}`,
        },
        true
      );
      if (!result.ok) throw new Error(result.message || "批次删除失败");
      const counts = result.deleted_counts || {};
      const message = `批次已删除：物料 ${counts.item_count || 0}，版本 ${counts.version_count || 0}，规则 ${counts.rule_count || 0}`;
      frappe.show_alert({ message, indicator: "green" });
      if (this.activeBatchName === batch.name) this.activeBatchName = "";
      delete this.batchItems[batch.name];
      this.expandedBatchNames.delete(batch.name);
      await this.loadBatches();
    } catch (error) {
      this.showError(error);
    }
  }

  openAddBatchDialog() {
    const dialog = new frappe.ui.Dialog({
      title: "添加报关运单",
      fields: [
        { fieldtype: "Data", fieldname: "batch_no", label: "批次号/来源单号", reqd: 1 },
        { fieldtype: "Data", fieldname: "customs_no", label: "报关单号" },
        { fieldtype: "Data", fieldname: "waybill_no", label: "运单号/物流单号" },
        { fieldtype: "Data", fieldname: "container_no", label: "柜号" },
        { fieldtype: "Select", fieldname: "transport_mode", label: "运输方式", options: "海运\n空运\n快递", default: "海运" },
        {
          fieldtype: "Select",
          fieldname: "business_type",
          label: "业务类型",
          options: "海运正报正清\n海运 DDP（双清包税）\n空运 DDP（双清包税）\n正常空运\n快递",
          default: "海运正报正清",
        },
        { fieldtype: "Data", fieldname: "project_collection", label: "项目归集" },
        { fieldtype: "Data", fieldname: "source_approval_no", label: "钉钉审批编号" },
        { fieldtype: "Data", fieldname: "source_instance_id", label: "钉钉实例ID（procInstId）" },
        { fieldtype: "Small Text", fieldname: "source_dingtalk_url", label: "钉钉审批链接" },
        { fieldtype: "Small Text", fieldname: "source_remark", label: "备注" },
      ],
      primary_action_label: "确认新增",
      primary_action: (values) => {
        const batchPayload = {
          ...values,
          batch_no: String(values.batch_no || "").trim(),
          customs_no: String(values.customs_no || "").trim(),
          waybill_no: String(values.waybill_no || "").trim(),
          container_no: String(values.container_no || "").trim(),
          source_instance_id: String(values.source_instance_id || "").trim(),
          source_dingtalk_url: String(values.source_dingtalk_url || "").trim(),
        };
        const label = batchPayload.customs_no || batchPayload.waybill_no || batchPayload.batch_no;
        frappe.confirm(
          `
            <div class="ocw-confirm-copy">
              <h4>确认新增报关运单？</h4>
              <p>将新增「${this.escape(label || "未命名批次")}」空白批次。</p>
              <div class="ocw-confirm-note">新增后可继续添加物料或导入附件补数。</div>
            </div>
          `,
          async () => {
            const created = await this.createBatch(batchPayload);
            if (created) dialog.hide();
          }
        );
      },
    });
    dialog.show();
  }

  async createBatch(batchPayload) {
    try {
      const result = await this.call(
        "overseas_costing.api.batch.create_batch",
        {
          batch_payload: JSON.stringify(batchPayload),
        },
        true
      );
      if (!result.ok) throw new Error(result.message || "新增报关运单失败");
      this.resetFilterValues();
      this.activeBatchName = result.batch_name || "";
      await this.loadBatches();
      if (result.batch_name) {
        const batch = this.findBatch(result.batch_name);
        await this.loadBatchItems(result.batch_name, batch ? batch.current_version : result.version_name, true);
        this.expandedBatchNames.add(result.batch_name);
        this.renderTable();
        this.updateSearchResult();
      }
      frappe.show_alert({ message: result.message || "报关运单已新增", indicator: "green" });
      return true;
    } catch (error) {
      this.showError(error);
      return false;
    }
  }

  openAddMaterialDialog(batchName) {
    const batch = this.findBatch(batchName);
    if (!batch) return;
    this.activeBatchName = batch.name;
    this.exportPinnedBatchName = batch.name;
    const dialog = new frappe.ui.Dialog({
      title: "添加新物料",
      fields: [
        { fieldtype: "Data", fieldname: "material_code", label: "物料编码", reqd: 1 },
        { fieldtype: "Data", fieldname: "product_name", label: "物料名称（中文）", reqd: 1 },
        { fieldtype: "Data", fieldname: "product_name_es", label: "物料名称（西语）" },
        { fieldtype: "Data", fieldname: "spec_model", label: "规格型号 Especificación / Modelo" },
        { fieldtype: "Float", fieldname: "unit_price", label: "采购单价", default: 0 },
        { fieldtype: "Float", fieldname: "quantity", label: "采购数量", default: 1 },
        { fieldtype: "Data", fieldname: "unit", label: "单位" },
        { fieldtype: "Data", fieldname: "recipient", label: "收件人" },
        { fieldtype: "Data", fieldname: "import_name", label: "海关进口名称" },
        { fieldtype: "Data", fieldname: "hs_code", label: "海关分类编码" },
        { fieldtype: "Data", fieldname: "category", label: "大类分类" },
      ],
      primary_action_label: "确认新增",
      primary_action: (values) => {
        const itemPayload = {
          ...values,
          transport_mode: batch.transport_mode || "SEA",
          customs_no: batch.customs_no || "",
          waybill_no: batch.waybill_no || "",
          goods_value: Number(values.unit_price || 0) * Number(values.quantity || 0),
        };
        frappe.confirm(
          `
            <div class="ocw-confirm-copy">
              <h4>确认新增物料？</h4>
              <p>将在 ${this.escape(batch.waybill_no || batch.batch_no || batch.name)} 下新增「${this.escape(values.product_name || values.material_code)}」。</p>
            </div>
          `,
          async () => {
            const created = await this.createMaterial(batch, itemPayload);
            if (created) dialog.hide();
          }
        );
      },
    });
    dialog.show();
  }

  async createMaterial(batch, itemPayload) {
    try {
      const result = await this.call(
        "overseas_costing.api.calculate.create_item",
        {
          batch_name: batch.name,
          version_name: batch.current_version,
          item_payload: JSON.stringify(itemPayload),
          remark: "前端添加新物料",
        },
        true
      );
      if (!result.ok) throw new Error(result.message || "新增物料失败");
      this.markBatchDirty(batch.name);
      this.resetFilterValues();
      await this.loadBatchItems(batch.name, batch.current_version, true);
      await this.loadAuditLogs(batch.name, batch.current_version);
      this.expandedBatchNames.add(batch.name);
      this.renderTable();
      this.updateSearchResult();
      frappe.show_alert({ message: result.message || "物料已新增", indicator: "green" });
      return true;
    } catch (error) {
      this.showError(error);
      return false;
    }
  }

  confirmDeleteMaterial(batchName, itemName, itemLabel) {
    const batch = this.findBatch(batchName);
    if (!batch || !itemName) return;
    frappe.confirm(
      `
        <div class="ocw-confirm-copy">
          <h4>确认删除物料？</h4>
          <p>将从 ${this.escape(batch.waybill_no || batch.batch_no || batch.name)} 下删除物料：${this.escape(itemLabel || itemName)}。</p>
          <div class="ocw-confirm-note">删除后批次会标记为 Dirty，并写入修改记录。</div>
        </div>
      `,
      async () => {
        await this.deleteMaterial(batch, itemName, itemLabel);
      }
    );
  }

  async deleteMaterial(batch, itemName, itemLabel) {
    try {
      const result = await this.call(
        "overseas_costing.api.calculate.delete_item",
        {
          item_name: itemName,
          batch_name: batch.name,
          version_name: batch.current_version,
          remark: `前端删除物料：${itemLabel || itemName}`,
        },
        true
      );
      if (!result.ok) throw new Error(result.message || "删除物料失败");
      this.markBatchDirty(batch.name);
      await this.loadBatchItems(batch.name, batch.current_version, true);
      await this.loadAuditLogs(batch.name, batch.current_version);
      this.expandedBatchNames.add(batch.name);
      this.renderTable();
      frappe.show_alert({ message: result.message || "物料已删除", indicator: "green" });
    } catch (error) {
      this.showError(error);
    }
  }

  startCellEdit($cell, event = null, autoOpenSelect = false) {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    if (!$cell.length || $cell.data("saving") || $cell.hasClass("is-editing")) return;
    if ($cell.attr("data-editable-cell") !== "1") return;

    const fieldname = $cell.attr("data-fieldname");
    const oldValue = $cell.attr("data-raw-value") || "";
    const label = $cell.attr("data-field-label") || fieldname;
    const isNumeric = this.isNumericField(fieldname);
    const options = this.selectOptions[fieldname] || null;
    const selectedValue = options ? this.normalizeSelectValue(fieldname, oldValue) : oldValue;

    $cell.removeData("cancelled saving");
    $cell.data("original-html", $cell.html());
    $cell.addClass("is-editing");

    if (options) {
      const hasSelectedOption = options.some((option) => String(option) === selectedValue);
      const emptyOption = selectedValue ? "" : `<option value="" selected>请选择</option>`;
      const currentOption =
        selectedValue && !hasSelectedOption
          ? `<option value="${this.escape(selectedValue)}" selected>${this.escape(this.selectOptionLabel(fieldname, selectedValue))}</option>`
          : "";
      const optionHtml = options
        .map(
          (option) =>
            `<option value="${this.escape(option)}" ${String(option) === selectedValue ? "selected" : ""}>${this.escape(this.selectOptionLabel(fieldname, option))}</option>`
        )
        .join("");
      $cell.html(`<select class="ocw-cell-editor ocw-cell-select" aria-label="${this.escape(label)}">${emptyOption}${currentOption}${optionHtml}</select>`);
    } else {
      $cell.html(`
        <input
          class="ocw-cell-editor"
          aria-label="${this.escape(label)}"
          value="${this.escape(oldValue)}"
          ${isNumeric ? 'inputmode="decimal"' : ""}
        />
      `);
    }

    const editor = $cell.find(".ocw-cell-editor").get(0);
    if (editor) {
      if (autoOpenSelect && options && typeof editor.showPicker === "function") {
        editor.focus();
        try {
          editor.showPicker();
          return;
        } catch (error) {
          // Some browsers only allow showPicker in stricter user-gesture windows.
        }
      }
      window.requestAnimationFrame(() => {
        editor.focus();
        if (editor.setSelectionRange && editor.value !== undefined) {
          const pos = String(editor.value).length;
          editor.setSelectionRange(pos, pos);
        }
      });
    }
  }

  cancelCellEdit($cell) {
    if (!$cell.length || !$cell.hasClass("is-editing")) return;
    $cell.data("cancelled", true);
    $cell.removeData("saving committing");
    $cell.removeClass("is-editing is-saving");
    $cell.html($cell.data("original-html") || this.renderCell($cell.attr("data-raw-value"), { fieldname: $cell.attr("data-fieldname") }));
  }

  async commitCellEdit($cell) {
    if (!$cell.length || !$cell.hasClass("is-editing") || $cell.data("saving") || $cell.data("committing") || $cell.data("cancelled")) {
      $cell.removeData("cancelled");
      return;
    }
    $cell.data("committing", true);

    const $editor = $cell.find(".ocw-cell-editor");
    const oldValue = $cell.attr("data-raw-value") || "";
    const fieldname = $cell.attr("data-fieldname");
    const newValue = this.selectOptions[fieldname] ? this.normalizeSelectValue(fieldname, $editor.val()) : this.normalizeEditorValue($editor.val());
    const oldComparableValue = this.selectOptions[fieldname] ? this.normalizeSelectValue(fieldname, oldValue) : oldValue;
    const fieldLabel = $cell.attr("data-field-label") || fieldname;
    const batchName = $cell.attr("data-batch-name");
    const itemName = $cell.attr("data-item-name");
    const versionName = $cell.attr("data-version-name") || null;
    const isSpecialOverride = $cell.attr("data-special-override") === "1";
    const itemLabel = this.getLocalItemLabel(batchName, itemName);

    if (newValue === oldComparableValue) {
      this.cancelCellEdit($cell);
      return;
    }

    const confirmed = await this.requestEditConfirm(fieldLabel, this.formatCellValue(newValue, { fieldname }));
    if (!confirmed) {
      this.cancelCellEdit($cell);
      return;
    }

    let remark = "";
    if (isSpecialOverride) {
      remark = await this.requestEditRemark(fieldLabel);
      if (!remark) {
        this.cancelCellEdit($cell);
        return;
      }
    }

    $cell.data("saving", true).addClass("is-saving").html(`<span class="ocw-cell-saving">保存中</span>`);
    try {
      const result = await this.call(
        "overseas_costing.api.calculate.update_item_field",
        {
          item_name: itemName,
          fieldname,
          value: newValue,
          version_name: versionName,
          remark,
        },
        true
      );
      if (!result.ok) {
        throw new Error(result.message || "字段保存失败");
      }
      this.activeBatchName = batchName;
      this.markBatchDirty(batchName);
      this.updateLocalItemValue(batchName, itemName, fieldname, result.value);
      await this.loadBatchItems(batchName, versionName, true);
      await this.loadAuditLogs(batchName, versionName);
      this.renderTable();
      frappe.show_alert({ message: result.message || "字段已保存", indicator: result.changed ? "green" : "blue" });
    } catch (error) {
      $cell.removeData("saving committing");
      this.cancelCellEdit($cell);
      this.showError(error);
    }
  }

  requestEditConfirm(fieldLabel, newValue) {
    return new Promise((resolve) => {
      frappe.confirm(
        `
          <div class="ocw-confirm-copy">
            <h4>确认修改</h4>
            <p>确认将「${this.escape(fieldLabel)}」修改为「${this.escape(this.formatValue(newValue))}」？</p>
          </div>
        `,
        () => resolve(true),
        () => resolve(false)
      );
    });
  }

  requestEditRemark(fieldLabel) {
    return new Promise((resolve) => {
      let settled = false;
      const dialog = new frappe.ui.Dialog({
        title: "填写修改原因",
        fields: [
          {
            fieldtype: "Small Text",
            fieldname: "remark",
            label: `${fieldLabel} 修改原因`,
            reqd: 1,
          },
        ],
        primary_action_label: "保存",
        primary_action: (values) => {
          settled = true;
          dialog.hide();
          resolve(String(values.remark || "").trim());
        },
      });
      dialog.onhide = () => {
        if (!settled) resolve("");
      };
      dialog.show();
    });
  }

  markBatchDirty(batchName) {
    const batch = this.findBatch(batchName);
    if (batch) batch.status = "Dirty";
  }

  updateLocalItemValue(batchName, itemName, fieldname, value) {
    const items = this.batchItems[batchName] || [];
    const row = items.find((item) => item.name === itemName);
    if (!row) return;
    row[fieldname] = value;
    row.manual_override_flag = 1;
  }

  getLocalItemLabel(batchName, itemName) {
    const items = this.batchItems[batchName] || [];
    const row = items.find((item) => item.name === itemName);
    if (!row) return "";
    return this.materialAuditLabel(row);
  }

  materialAuditLabel(row) {
    if (!row) return "";
    const code = row.material_code || "";
    const name = row.product_name || "";
    if (code && name) return `${code} / ${name}`;
    return code || name || row.name || "未命名物料";
  }

