# -*- coding: utf-8 -*-
from datetime import date
from odoo import api, fields, models, _


class HrLeave(models.Model):
    _inherit = 'hr.leave'

    consumption_ids = fields.One2many(
        'hr.leave.allocation.consumption',
        'leave_id',
        string='FIFO Allocation Consumptions',
        readonly=True,
    )

    def action_validate(self, check_state=True):
        res = super().action_validate(check_state=check_state)
        self._record_fifo_consumptions()
        return res

    def action_refuse(self):
        res = super().action_refuse()
        self._clear_fifo_consumptions()
        return res

    def action_cancel(self):
        res = super().action_cancel()
        self._clear_fifo_consumptions()
        return res

    def action_reset_confirm(self):
        res = super().action_reset_confirm()
        self._clear_fifo_consumptions()
        return res

    def _record_fifo_consumptions(self):
        Consumption = self.env['hr.leave.allocation.consumption'].sudo()
        Alloc = self.env['hr.leave.allocation'].sudo()

        for leave in self.filtered(lambda l: l.state == 'validate' and l.holiday_status_id.requires_allocation == 'yes'):
            # Clear previous consumptions for this leave
            leave.consumption_ids.sudo().unlink()

            allocs = Alloc.search([
                ('employee_id', '=', leave.employee_id.id),
                ('holiday_status_id', '=', leave.holiday_status_id.id),
                ('state', '=', 'validate'),
                ('date_from', '<=', leave.date_to.date()),
                '|', ('date_to', '=', False), ('date_to', '>=', leave.date_from.date()),
            ])
            if not allocs:
                continue

            # Row-level locking to prevent concurrent overconsumption
            self.env.cr.execute(
                'SELECT id FROM hr_leave_allocation WHERE id IN %s FOR UPDATE',
                [tuple(allocs.ids)]
            )

            # Sort strictly by FIFO:
            # 1. Earliest expiry (date_to)
            # 2. Earliest start date (date_from)
            # 3. Deterministic allocation ID
            def fifo_sort_key(a):
                dt = a.date_to or date.max
                df = a.date_from or (a.create_date.date() if a.create_date else date.min)
                return (dt, df, a.id)

            sorted_allocs = allocs.sorted(key=fifo_sort_key)
            remaining_to_consume = leave.number_of_days

            for alloc in sorted_allocs:
                if remaining_to_consume <= 0:
                    break

                # Calculate days already consumed on this allocation by other validated leaves
                other_consumptions = Consumption.search([
                    ('allocation_id', '=', alloc.id),
                    ('leave_id', '!=', leave.id),
                    ('state', '=', 'validate'),
                ])
                already_taken = sum(other_consumptions.mapped('consumed_days'))
                encashed = alloc.encashed_days or 0.0
                expired = alloc.expired_days or 0.0

                free_days = max(0.0, alloc.number_of_days - already_taken - encashed - expired)
                if free_days <= 0:
                    continue

                take = min(free_days, remaining_to_consume)
                Consumption.create({
                    'allocation_id': alloc.id,
                    'leave_id': leave.id,
                    'employee_id': leave.employee_id.id,
                    'leave_type_id': leave.holiday_status_id.id,
                    'consumed_days': take,
                    'consumption_date': leave.date_from.date(),
                })
                remaining_to_consume -= take

    def _clear_fifo_consumptions(self):
        for leave in self:
            leave.consumption_ids.sudo().unlink()
