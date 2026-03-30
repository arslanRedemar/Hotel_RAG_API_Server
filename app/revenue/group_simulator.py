"""단체 예약 시뮬레이터 — 수락/거절/협상 권고"""

from datetime import date, timedelta

from app.revenue.crud import get_current_pms_rate, get_demand_forecast


class GroupBookingSimulator:
    def simulate(
        self,
        rooms_requested: int,
        check_in: date,
        check_out: date,
        proposed_rate: float,
    ) -> dict:
        nights = (check_out - check_in).days
        total_room_nights = rooms_requested * nights

        # 시나리오 1: 단체 수락
        accept_revenue = proposed_rate * total_room_nights

        # 시나리오 2: 단체 거절 시 개별 예약으로 채울 경우
        reject_revenue = 0.0
        opportunity_breakdown = []

        for day_offset in range(nights):
            stay_date = check_in + timedelta(days=day_offset)
            forecast = get_demand_forecast(stay_date)
            base_rate = get_current_pms_rate(stay_date)

            expected_occ = (
                forecast["predicted_occupancy_base"] if forecast else 70.0
            ) / 100
            expected_fill = min(rooms_requested, round(rooms_requested * expected_occ))
            day_revenue = expected_fill * base_rate

            reject_revenue += day_revenue
            opportunity_breakdown.append(
                {
                    "date": stay_date.isoformat(),
                    "expected_fill": expected_fill,
                    "rate": base_rate,
                    "revenue": day_revenue,
                }
            )

        opportunity_cost = accept_revenue - reject_revenue

        # 권고 결정
        if accept_revenue > reject_revenue * 1.05:  # 단체가 5% 이상 유리
            recommendation = "accept"
            note = (
                f"단체 수락 시 확정 수익 {accept_revenue:,.0f}원이 개별 예약 기대치"
                f"({reject_revenue:,.0f}원)보다 "
                f"{(accept_revenue / reject_revenue - 1) * 100:.0f}% 유리합니다."
                if reject_revenue > 0
                else f"단체 수락 시 확정 수익 {accept_revenue:,.0f}원이 개별 예약 기대치보다 유리합니다."
            )
        elif accept_revenue < reject_revenue * 0.85:  # 단체가 15% 이상 불리
            recommendation = "reject"
            note = (
                f"개별 예약 기대 수익({reject_revenue:,.0f}원)이 단체 수익"
                f"({accept_revenue:,.0f}원)보다 높습니다. 거절 권고."
            )
        else:
            recommendation = "negotiate"
            note = (
                "수익 차이가 미미합니다. 취소 패널티 강화 또는 F&B 마진 재협상 "
                "조건으로 수락을 고려하세요."
            )

        return {
            "accept_revenue": accept_revenue,
            "reject_revenue": reject_revenue,
            "opportunity_cost": opportunity_cost,
            "recommendation": recommendation,
            "recommendation_note": note,
            "nights": nights,
            "total_room_nights": total_room_nights,
            "daily_breakdown": opportunity_breakdown,
        }
