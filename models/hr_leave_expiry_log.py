# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class HrLeaveExpiryLog(models.Model):
    _name = 'hr.leave.expiry.log'
    _description = 'Expired Leave Log'
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Log Reference',
        compute='_compute_name',
        store=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        index=True,
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        related='employee_id.department_id',
        store=True,
        index=True,
    )
    holiday_status_id = fields.Many2one(
        'hr.leave.type',
        string='Time Off Type',
        required=True,
        index=True,
    )
    allocation_id = fields.Many2one(
        'hr.leave.allocation',
        string='Original Allocation',
        ondelete='set null',
        index=True,
    )
    allocation_date = fields.Date(
        string='Allocation Start Date',
    )
    expiry_date = fields.Date(
        string='Expiry Date',
    )
    allocated_days = fields.Float(
        string='Originally Allocated Days',
        digits=(16, 2),
    )
    utilized_days = fields.Float(
        string='Days Already Utilized',
        digits=(16, 2),
    )
    expired_days = fields.Float(
        string='Remaining Days Expired',
        digits=(16, 2),
        required=True,
    )
    date = fields.Date(
        string='Expiry Processing Date',
        default=fields.Date.context_today,
        required=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='employee_id.company_id',
        store=True,
        index=True,
    )

    @api.depends('employee_id.name', 'holiday_status_id.name', 'expired_days', 'date')
    def _compute_name(self):
        for rec in self:
            emp = rec.employee_id.name or _('Employee')
            lt = rec.holiday_status_id.name or _('Leave')
            rec.name = f"{emp} - {lt} ({rec.expired_days} d expired on {rec.date})"
