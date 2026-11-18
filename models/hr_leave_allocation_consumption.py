# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class HrLeaveAllocationConsumption(models.Model):
    _name = 'hr.leave.allocation.consumption'
    _description = 'Leave Allocation FIFO Consumption'
    _order = 'consumption_date desc, id desc'

    name = fields.Char(
        string='Consumption Reference',
        compute='_compute_name',
        store=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        index=True,
        ondelete='cascade',
    )
    allocation_id = fields.Many2one(
        'hr.leave.allocation',
        string='Original Allocation',
        required=True,
        index=True,
        ondelete='cascade',
    )
    leave_id = fields.Many2one(
        'hr.leave',
        string='Time Off Request',
        required=True,
        index=True,
        ondelete='cascade',
    )
    leave_type_id = fields.Many2one(
        'hr.leave.type',
        string='Time Off Type',
        required=True,
        index=True,
    )
    consumed_days = fields.Float(
        string='Consumed Days',
        required=True,
        digits=(16, 2),
    )
    consumption_date = fields.Date(
        string='Consumption Date',
        default=fields.Date.context_today,
        required=True,
    )
    allocation_expiry_date = fields.Date(
        string='Allocation Expiry Date',
        related='allocation_id.date_to',
        readonly=True,
    )
    state = fields.Selection([
        ('draft', 'To Submit'),
        ('confirm', 'To Approve'),
        ('refuse', 'Refused'),
        ('validate1', 'Second Approval'),
        ('validate', 'Approved'),
        ('cancel', 'Cancelled'),
    ], string='Status', related='leave_id.state', store=True, index=True)

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='employee_id.company_id',
        store=True,
        index=True,
    )

    @api.depends('allocation_id.name', 'leave_id.name', 'consumed_days')
    def _compute_name(self):
        for rec in self:
            leave_name = rec.leave_id.display_name or rec.leave_id.name or _('Leave')
            alloc_name = rec.allocation_id.display_name or rec.allocation_id.name or _('Allocation')
            rec.name = f"{alloc_name} -> {leave_name} ({rec.consumed_days} d)"
