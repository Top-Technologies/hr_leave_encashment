# -*- coding: utf-8 -*-
from datetime import date
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _


class HrLeaveAllocation(models.Model):
    _inherit = 'hr.leave.allocation'

    validity_years = fields.Integer(
        string='Validity (Years)',
        related='holiday_status_id.validity_years',
        readonly=True,
    )
    expiry_processed = fields.Boolean(
        string='Expiry Processed',
        default=False,
        copy=False,
        tracking=True,
    )
    expired_days = fields.Float(
        string='Expired Days',
        default=0.0,
        copy=False,
        digits=(16, 2),
        tracking=True,
    )
    encashed_days = fields.Float(
        string='Encashed Days',
        compute='_compute_encashed_days',
        store=True,
        digits=(16, 2),
        tracking=True,
    )
    encashment_line_ids = fields.One2many(
        'hr.leave.encashment.line',
        'allocation_id',
        string='Encashment Lines',
    )
    consumption_ids = fields.One2many(
        'hr.leave.allocation.consumption',
        'allocation_id',
        string='FIFO Consumptions',
    )
    consumed_leave_days = fields.Float(
        string='Utilized Days',
        compute='_compute_consumed_leave_days',
        store=True,
        digits=(16, 2),
    )
    remaining_balance = fields.Float(
        string='Available Balance',
        compute='_compute_remaining_balance',
        digits=(16, 2),
    )
    is_expired = fields.Boolean(
        string='Is Expired',
        compute='_compute_is_expired',
        store=True,
    )

    @api.depends('employee_id', 'holiday_status_id', 'consumption_ids.consumed_days', 'consumption_ids.state')
    def _compute_leaves(self):
        super()._compute_leaves()
        for alloc in self:
            fifo_consumed = sum(
                alloc.consumption_ids.filtered(lambda c: c.state == 'validate').mapped('consumed_days')
            )
            if fifo_consumed > 0:
                alloc.leaves_taken = max(round(fifo_consumed, 2), round(alloc.leaves_taken or 0.0, 2))

    @api.depends('encashment_line_ids', 'encashment_line_ids.days', 'encashment_line_ids.encashment_id.state')
    def _compute_encashed_days(self):
        for alloc in self:
            valid_lines = alloc.encashment_line_ids.filtered(
                lambda l: l.encashment_id.state in ('approved', 'sent_to_payroll', 'paid')
            )
            alloc.encashed_days = sum(valid_lines.mapped('days'))

    @api.depends('date_to')
    def _compute_is_expired(self):
        today = fields.Date.context_today(self)
        for alloc in self:
            alloc.is_expired = bool(alloc.date_to and alloc.date_to < today)

    @api.depends('consumption_ids.consumed_days', 'consumption_ids.state', 'leaves_taken')
    def _compute_consumed_leave_days(self):
        for alloc in self:
            fifo_consumed = sum(
                alloc.consumption_ids.filtered(lambda c: c.state == 'validate').mapped('consumed_days')
            )
            alloc.consumed_leave_days = max(round(fifo_consumed, 2), round(alloc.leaves_taken or 0.0, 2))

    @api.depends('number_of_days', 'consumed_leave_days', 'leaves_taken', 'encashed_days', 'expired_days', 'date_to', 'consumption_ids.consumed_days', 'consumption_ids.state')
    def _compute_remaining_balance(self):
        today = fields.Date.context_today(self)
        for alloc in self:
            if alloc.date_to and alloc.date_to < today:
                alloc.remaining_balance = 0.0
            else:
                utilized = alloc.consumed_leave_days if hasattr(alloc, 'consumed_leave_days') else (alloc.leaves_taken or 0.0)
                free = alloc.number_of_days - (utilized or 0.0) - (alloc.encashed_days or 0.0) - (alloc.expired_days or 0.0)
                alloc.remaining_balance = max(0.0, round(free, 2))

    @api.model_create_multi
    def create(self, vals_list):
        LeaveType = self.env['hr.leave.type']
        for vals in vals_list:
            if vals.get('date_to') or not vals.get('holiday_status_id'):
                continue
            leave_type = LeaveType.browse(vals['holiday_status_id'])
            if leave_type.validity_years > 0:
                start = fields.Date.to_date(vals.get('date_from')) or fields.Date.context_today(self)
                vals['date_to'] = start + relativedelta(years=leave_type.validity_years, days=-1)
        return super().create(vals_list)

    def action_validate(self):
        for alloc in self:
            if not alloc.date_to and alloc.holiday_status_id.validity_years > 0:
                start = alloc.date_from or fields.Date.context_today(alloc)
                alloc.date_to = start + relativedelta(years=alloc.holiday_status_id.validity_years, days=-1)
        return super().action_validate()

    @api.model
    def _cron_log_expired_allocations(self):
        """
        Scheduled action to identify approved allocations whose 2-year (or configured) validity has expired,
        log the expired unused days in hr.leave.expiry.log, and record expired_days on the allocation.
        Original number_of_days is preserved.
        """
        today = fields.Date.context_today(self)
        expired_allocs = self.search([
            ('state', '=', 'validate'),
            ('date_to', '<', today),
            ('expiry_processed', '=', False),
            ('holiday_status_id.validity_years', '>', 0),
        ])
        Log = self.env['hr.leave.expiry.log']
        for alloc in expired_allocs:
            utilized = alloc.consumed_leave_days or alloc.leaves_taken or 0.0
            remaining = max(0.0, alloc.number_of_days - utilized - (alloc.encashed_days or 0.0))
            if remaining > 0:
                Log.create({
                    'allocation_id': alloc.id,
                    'employee_id': alloc.employee_id.id,
                    'holiday_status_id': alloc.holiday_status_id.id,
                    'allocation_date': alloc.date_from,
                    'expiry_date': alloc.date_to,
                    'allocated_days': alloc.number_of_days,
                    'utilized_days': utilized,
                    'expired_days': remaining,
                    'date': today,
                })
                alloc.expired_days = remaining
            alloc.expiry_processed = True
            alloc.message_post(body=_(
                "Allocation validity expired on %s. Unused days expired: %s day(s).",
                alloc.date_to, remaining
            ))

    @api.model
    def _cron_generate_encashment_drafts(self, days_before=30):
        today = fields.Date.context_today(self)
        limit = today + relativedelta(days=days_before)
        allocs = self.search([
            ('state', '=', 'validate'),
            ('date_to', '>=', today),
            ('date_to', '<=', limit),
            ('holiday_status_id.encashable', '=', True),
            ('employee_id', '!=', False),
        ])
        Enc = self.env['hr.leave.encashment']
        done = set()
        for alloc in allocs:
            key = (alloc.employee_id.id, alloc.holiday_status_id.id)
            if key in done:
                continue
            done.add(key)
            exists = Enc.search_count([
                ('employee_id', '=', alloc.employee_id.id),
                ('holiday_status_id', '=', alloc.holiday_status_id.id),
                ('state', 'in', ('draft', 'submitted', 'approved', 'sent_to_payroll')),
            ])
            if exists:
                continue
            rec = Enc.create({
                'employee_id': alloc.employee_id.id,
                'holiday_status_id': alloc.holiday_status_id.id,
                'date': today,
                'auto_generated': True,
            })
            if rec.days_available > 0:
                rec.days_to_encash = rec.days_available
            else:
                rec.unlink()
