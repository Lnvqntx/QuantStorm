# Name: Lnv Lochan Ch
# College: IIT Madras
# Roll Number: 25f2003773

"""
my_bot.py — Divided Oracle: QuantStorm 2026 Round 1  (v4)
===========================================================
"""

import math
import random

POWER_VALUES = {
    "FORESIGHT":    {1: 0.76, 2: 1.16, 3: 1.48, 4: 1.97, 5: 2.02},
    "TRICK_ROOM":   {1: 1.25, 2: 0.00, 3: 0.00, 4: 0.66, 5: 0.57},
    "SUBSTITUTE":   {1: 1.46, 2: 1.15, 3: 0.95, 4: 0.57, 5: 0.29},
    "STEALTH_ROCK": {1: 1.66, 2: 0.83, 3: 0.83, 4: 0.83, 5: 0.00},
    "TRANSFORM":    {1: 1.58, 2: 1.24, 3: 1.31, 4: 0.00, 5: 0.00},
}

SHADE = 0.60
FLAT_THRESHOLD = 1
OPP_FLAT_THRESHOLD = 2.0
DENIAL_WEIGHT = 0.0

SHIFT_POWERS = {"TRICK_ROOM": 3, "STEALTH_ROCK": 2}
N_THEIR_COINS = 20
SUBSTITUTE_FLOOR = -2.0

_SQRT2 = math.sqrt(2.0)
_SQRT2PI = math.sqrt(2.0 * math.pi)


class Bot:
    name = "MyBot"

    def reset(self, seat, config, seed):
        self.seat = seat
        self.config = config
        self.rng = random.Random(seed)

        self._opp_anchor = {}
        self._foresight_signal = None
        self._quote_signal = None

    
    def _update_signals(self, obs, quote):
        if obs.foresight:
            n = len(obs.foresight)
            var = max(1.0, N_THEIR_COINS - n)
            if self._foresight_signal is None or var < self._foresight_signal[1]:
                self._foresight_signal = (float(sum(obs.foresight)), var)

        if not obs.is_maker and quote is not None:
            r = obs.round
            if r not in self._opp_anchor:
                est = (quote[0] + quote[1]) / 2.0
                self._opp_anchor[r] = est
                var = max(1.0, N_THEIR_COINS - self.config.REVEAL_PER_ROUND * r)
                if self._quote_signal is None or var < self._quote_signal[1]:
                    self._quote_signal = (est, var)

    def _opp_posterior(self):
       
        sigs = [s for s in (self._foresight_signal, self._quote_signal) if s is not None]
        if not sigs:
            return 0.0, float(N_THEIR_COINS)
        num = sum(v / var for v, var in sigs)
        den = sum(1.0 / var for _, var in sigs)
        return num / den, 1.0 / den

    def _opponent_k(self, obs):
       
        earlier = [k for k in self._opp_anchor if k < obs.round]
        if self._quote_signal is not None and earlier:
            return self._quote_signal[0]
        if not earlier:
            return None
        return self._opp_anchor[max(earlier)]

    def _value(self, obs, quote=None):
        self._update_signals(obs, quote)
        opp_mean, _ = self._opp_posterior()
        return float(obs.k_mine) + opp_mean

    def _residual_sd(self, obs):
        
        self._update_signals(obs, None)
        mine_unseen = max(0, self.config.N_PRIVATE - len(obs.my_revealed))
        _, opp_var = self._opp_posterior()
        return math.sqrt(max(1e-9, mine_unseen + opp_var))

    
    @staticmethod
    def _norm_cdf(x):
        return 0.5 * (1.0 + math.erf(x / _SQRT2))

    @staticmethod
    def _norm_pdf(x):
        return math.exp(-0.5 * x * x) / _SQRT2PI

    def _floor_bonus(self, edge, sd, floor=SUBSTITUTE_FLOOR):
        
        if sd <= 1e-9:
            return max(0.0, floor - edge)
        z = (floor - edge) / sd
        return (floor - edge) * self._norm_cdf(z) + sd * self._norm_pdf(z)

    

    def _power_value(self, obs, name):
        return POWER_VALUES.get(name, {}).get(obs.round, 0.5)

    def _transform_value(self, obs):
        swap = self._power_value(obs, "TRANSFORM")
        if abs(obs.k_mine) <= FLAT_THRESHOLD:
            return swap
        opp_k = self._opponent_k(obs)
        if opp_k is not None and abs(opp_k) <= OPP_FLAT_THRESHOLD:
            return swap * DENIAL_WEIGHT
        return 0.0

    def bid(self, obs, offered):
        if not offered or obs.te_mine <= 0:
            return {}
        
        raw = {}
        for name in offered:
            v = self._transform_value(obs) if name == "TRANSFORM" else self._power_value(obs, name)
            if v <= 0:
                continue
            fair_te = v / self.config.TE_SALVAGE
            raw[name] = fair_te * SHADE
        if not raw:
            return {}
        total = sum(raw.values())
        if total > obs.te_mine:
            scale = obs.te_mine / total
            raw = {k: v * scale for k, v in raw.items()}
        return {k: max(0, min(int(v), obs.te_mine)) for k, v in raw.items()}

    

    def quote(self, obs):
        v = round(self._value(obs, quote=None))
        fc, sc = obs.final_cap, obs.spread_cap
        w = fc
        if "FORESIGHT" in obs.powers_mine and obs.foresight:
            default_unseen = self.config.N_COINS - self.config.REVEAL_PER_ROUND * obs.round
            eff_unseen = default_unseen - len(obs.foresight)
            best_w, best_score = fc, None
            for cand in range(fc, sc + 1):
                real_p = self.config.straddle_prob(obs.round, cand, unseen=eff_unseen)
                cfg_p = self.config.straddle_prob(obs.round, cand)
                score = (self.config.MAKER_OBLIGATION * (real_p - cfg_p)
                         - self.config.WIDTH_PREMIUM * (cand - fc))
                if best_score is None or score > best_score:
                    best_score, best_w = score, cand
            w = best_w
        lo = v - w // 2
        return (lo, lo + w)

    

    def _net_shift_against_us(self, obs):
        theirs = sum(mag for name, mag in SHIFT_POWERS.items() if name in obs.powers_theirs)
        ours = sum(mag for name, mag in SHIFT_POWERS.items() if name in obs.powers_mine)
        return theirs - ours

    def _predicted_force_midpoint(self, obs, bid, ask):
        
        floor = obs.final_cap
        width = ask - bid
        max_width = min(width, max(floor, width - self.config.MIN_REDUCTION))
        target = floor  
        mid = ask
        nb = max(bid, mid - target // 2)
        na = min(ask, nb + target)
        nb = max(bid, na - target)
        return (nb + na) // 2

    def respond(self, obs, quote, turn):
        bid, ask = quote
        has_sub = "SUBSTITUTE" in obs.powers_mine

        if turn == self.config.N_TURNS:
            sd = self._residual_sd(obs) if has_sub else None
            v = self._value(obs, quote)
            shift = 0
            for name, mag in SHIFT_POWERS.items():
                if name in obs.powers_mine:
                    shift += mag
                if name in obs.powers_theirs:
                    shift -= mag

            predicted_mid = self._predicted_force_midpoint(obs, bid, ask)

            edge_buy = v - ask
            edge_sell = bid - v
            edge_force = (predicted_mid + shift - self.config.FORCED_FILL_FEE) - v

            if has_sub:
                edge_buy += self._floor_bonus(edge_buy, sd)
                edge_sell += self._floor_bonus(edge_sell, sd)
                
                force_contract_edge = (predicted_mid + shift) - v
                edge_force = (force_contract_edge + self._floor_bonus(force_contract_edge, sd)
                              - self.config.FORCED_FILL_FEE)

            best = max(edge_buy, edge_sell, edge_force)
            if best == edge_buy:
                return "ACCEPT_BUY"
            if best == edge_sell:
                return "ACCEPT_SELL"
            return ("COUNTER", ask, ask)

        v = self._value(obs, quote)
        edge_buy = v - ask
        edge_sell = bid - v

        thresh = 0.0

       
        net_shift = self._net_shift_against_us(obs)
        if turn == self.config.N_TURNS - 1:
            thresh -= net_shift * 0.6

        if edge_buy > thresh and edge_buy >= edge_sell:
            return "ACCEPT_BUY"
        if edge_sell > thresh:
            return "ACCEPT_SELL"

        floor = obs.final_cap
        w = max(floor, (ask - bid) - self.config.MIN_REDUCTION)
        w = min(w, ask - bid)
        center = max(bid, min(round(v), ask - w))
        return ("COUNTER", center, center + w)

    def use_transform(self, obs):
        return abs(obs.k_mine) <= FLAT_THRESHOLD