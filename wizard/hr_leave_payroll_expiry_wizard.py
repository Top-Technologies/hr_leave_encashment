# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class HrLeavePayrollExpiryWizard(models.TransientModel):
    _name = 'hr.leave.payroll.expiry.wizard'
    _description = 'HR Payroll Expiry Wizard'

    encashment_id = fields.Many2one(
        'hr.leave.encashment',
        string='Leave Encashment',
        required=True,
        ondelete='cascade',
        default=lambda self: self.env.context.get('active_id'),
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        related='encashment_id.employee_id',
        readonly=True,
    )
    holiday_status_id = fields.Many2one(
        'hr.leave.type',
        string='Time Off Type',
        related='encashment_id.holiday_status_id',
        readonly=True,
    )
    days_to_encash = fields.Float(
        string='Days Encashed',
        related='encashment_id.days_to_encash',
        readonly=True,
    )
    amount = fields.Monetary(
        string='Payable Amount',
        related='encashment_id.amount',
        readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='encashment_id.currency_id',
    )
    payslip_id = fields.Many2one(
        'hr.payslip',
        string='Linked Payslip',
        related='encashment_id.payslip_id',
        readonly=True,
    )
    payroll_status = fields.Selection(
        string='Current Payroll Status',
        related='encashment_id.payroll_status',
        readonly=True,
    )
    expiry_reason = fields.Text(
        string='Expiry Reason / Justification',
        required=True,
        placeholder="Enter HR justification for expiring this unpaid encashment...",
    )

    def action_confirm_expiry(self):
        self.ensure_one()
        if not self.encashment_id:
            raise UserError(_("No leave encashment record selected."))
        self.encashment_id.action_expire_payroll(reason=self.expiry_reason)
        return {'type': 'ir.actions.act_window_close'}
