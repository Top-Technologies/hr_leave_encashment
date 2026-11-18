# -*- coding: utf-8 -*-
from collections import defaultdict
from datetime import datetime, time, date
import pytz

from odoo import api, fields, models


class HrEmployeeBase(models.AbstractModel):
    _inherit = 'hr.employee.base'

    def _get_consumed_leaves(self, leave_types, target_date=False, ignore_future=False):
        """
        Override _get_consumed_leaves to implement:
        1. Strict FIFO sorting for allocations:
           - Earliest expiry date (date_to)
           - Earliest start date (date_from)
           - Deterministic allocation ID
        2. Deduct encashed days (encashed_days) and expired days (expired_days)
           from allocation available capacity.
        """
        employees = self or self._get_contextual_employee()
        leaves_domain = [
            ('holiday_status_id', 'in', leave_types.ids),
            ('employee_id', 'in', employees.ids),
            ('state', 'in', ['confirm', 'validate1', 'validate']),
        ]
        if self.env.context.get('ignored_leave_ids'):
            leaves_domain.append(('id', 'not in', self.env.context.get('ignored_leave_ids')))

        if not target_date:
            target_date = fields.Date.today()
        if ignore_future:
            leaves_domain.append(('date_from', '<=', target_date))
        leaves = self.env['hr.leave'].search(leaves_domain)
        leaves_per_employee_type = defaultdict(lambda: defaultdict(lambda: self.env['hr.leave']))
        for leave in leaves:
            leaves_per_employee_type[leave.employee_id][leave.holiday_status_id] |= leave

        allocations = self.env['hr.leave.allocation'].with_context(active_test=False).search([
            ('employee_id', 'in', employees.ids),
            ('holiday_status_id', 'in', leave_types.ids),
            ('state', '=', 'validate'),
        ])
        allocations_per_employee_type = defaultdict(lambda: defaultdict(lambda: self.env['hr.leave.allocation']))
        for allocation in allocations:
            allocations_per_employee_type[allocation.employee_id][allocation.holiday_status_id] |= allocation

        allocations_leaves_consumed = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: 0))))
        to_recheck_leaves_per_leave_type = defaultdict(lambda:
            defaultdict(lambda: {
                'excess_days': defaultdict(lambda: {
                    'amount': 0,
                    'is_virtual': True,
                }),
                'exceeding_duration': 0,
                'to_recheck_leaves': self.env['hr.leave']
            })
        )

        for allocation in allocations:
            allocation_data = allocations_leaves_consumed[allocation.employee_id][allocation.holiday_status_id][allocation]
            future_leaves = 0
            if allocation.allocation_type == 'accrual':
                future_leaves = allocation._get_future_leaves_on(target_date)
            max_leaves = allocation.number_of_hours_display\
                if allocation.holiday_status_id.request_unit in ['hour']\
                else allocation.number_of_days_display
            max_leaves += future_leaves

            # FIFO & Expiry adjustment: deduct encashed and expired days from available leaves
            encashed = getattr(allocation, 'encashed_days', 0.0) or 0.0
            expired = getattr(allocation, 'expired_days', 0.0) or 0.0
            deductions = encashed + expired
            max_leaves = max(0.0, max_leaves - deductions)

            allocation_data.update({
                'max_leaves': max_leaves,
                'accrual_bonus': future_leaves,
                'virtual_remaining_leaves': max_leaves,
                'remaining_leaves': max_leaves,
                'leaves_taken': 0,
                'virtual_leaves_taken': 0,
            })

        for employee in employees:
            for leave_type in leave_types:
                # FIFO Sort: 1. Earliest expiry (date_to), 2. Earliest start (date_from), 3. Allocation ID
                def alloc_sort_key(alloc):
                    dt = alloc.date_to or date.max
                    df = alloc.date_from or (alloc.create_date.date() if alloc.create_date else date.min)
                    return (dt, df, alloc.id)

                sorted_leave_allocations = allocations_per_employee_type[employee][leave_type].sorted(key=alloc_sort_key)

                if leave_type.request_unit in ['day', 'half_day']:
                    leave_duration_field = 'number_of_days'
                    leave_unit = 'days'
                else:
                    leave_duration_field = 'number_of_hours'
                    leave_unit = 'hours'

                leave_type_data = allocations_leaves_consumed[employee][leave_type]
                for leave in leaves_per_employee_type[employee][leave_type].sorted('date_from'):
                    leave_duration = leave[leave_duration_field]
                    skip_excess = False

                    if sorted_leave_allocations.filtered(lambda alloc: alloc.allocation_type == 'accrual') and leave.date_from.date() > target_date:
                        to_recheck_leaves_per_leave_type[employee][leave_type]['to_recheck_leaves'] |= leave
                        skip_excess = True
                        continue

                    if leave_type.requires_allocation == 'yes':
                        for allocation in sorted_leave_allocations:
                            if allocation.date_from > leave.date_to.date() or (allocation.date_to and allocation.date_to < leave.date_from.date()):
                                continue
                            interval_start = max(
                                leave.date_from,
                                datetime.combine(allocation.date_from, time.min)
                            )
                            interval_end = min(
                                leave.date_to,
                                datetime.combine(allocation.date_to, time.max)
                                if allocation.date_to else leave.date_to
                            )
                            duration = leave[leave_duration_field]
                            if leave.date_from != interval_start or leave.date_to != interval_end:
                                duration_info = employee._get_calendar_attendances(interval_start.replace(tzinfo=pytz.UTC), interval_end.replace(tzinfo=pytz.UTC))
                                duration = duration_info['hours' if leave_unit == 'hours' else 'days']
                            max_allowed_duration = min(
                                duration,
                                leave_type_data[allocation]['virtual_remaining_leaves']
                            )

                            if not max_allowed_duration:
                                continue

                            allocated_time = min(max_allowed_duration, leave_duration)
                            leave_type_data[allocation]['virtual_leaves_taken'] += allocated_time
                            leave_type_data[allocation]['virtual_remaining_leaves'] -= allocated_time
                            if leave.state == 'validate':
                                leave_type_data[allocation]['leaves_taken'] += allocated_time
                                leave_type_data[allocation]['remaining_leaves'] -= allocated_time

                            leave_duration -= allocated_time
                            if not leave_duration:
                                break
                        if round(leave_duration, 2) > 0 and not skip_excess:
                            to_recheck_leaves_per_leave_type[employee][leave_type]['excess_days'][leave.date_to.date()] = {
                                'amount': leave_duration,
                                'is_virtual': leave.state != 'validate',
                                'leave_id': leave.id,
                            }
                    else:
                        if leave_unit == 'hours':
                            allocated_time = leave.number_of_hours
                        else:
                            allocated_time = leave.number_of_days
                        leave_type_data[False]['virtual_leaves_taken'] += allocated_time
                        leave_type_data[False]['virtual_remaining_leaves'] = 0
                        leave_type_data[False]['remaining_leaves'] = 0
                        if leave.state == 'validate':
                            leave_type_data[False]['leaves_taken'] += allocated_time

        for employee in to_recheck_leaves_per_leave_type:
            for leave_type in to_recheck_leaves_per_leave_type[employee]:
                content = to_recheck_leaves_per_leave_type[employee][leave_type]
                consumed_content = allocations_leaves_consumed[employee][leave_type]
                if content['to_recheck_leaves']:
                    date_to_simulate = max(content['to_recheck_leaves'].mapped('date_from')).date()
                    latest_accrual_bonus = 0
                    date_accrual_bonus = 0
                    virtual_remaining = 0
                    additional_leaves_duration = 0
                    for allocation in consumed_content:
                        latest_accrual_bonus += allocation and allocation._get_future_leaves_on(date_to_simulate)
                        date_accrual_bonus += consumed_content[allocation]['accrual_bonus']
                        virtual_remaining += consumed_content[allocation]['virtual_remaining_leaves']
                    for leave in content['to_recheck_leaves']:
                        additional_leaves_duration += leave[leave_duration_field]
                    if round(additional_leaves_duration - latest_accrual_bonus + date_accrual_bonus - virtual_remaining, 2) > 0:
                        content['exceeding_duration'] = round(additional_leaves_duration - latest_accrual_bonus + date_accrual_bonus - virtual_remaining, 2)

        return allocations_leaves_consumed, to_recheck_leaves_per_leave_type
