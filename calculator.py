"""Arbitrary-precision expression calculator.

Code structure:
     1. Imports
     2. Internal variables
     3. Number
     4. Variable
     5. Lambda
     6. String
     7. Set
     8. Function
     9. Constant
    10. Command
    11. Expression engine
    12. Main
"""

# IMPORTS

import ast
import builtins
import contextlib
import decimal
import difflib
import inspect
import io
import json
import os
import re
import sys
import threading
import tokenize

import mpmath

try:
    import readline
except ImportError:
    pass


# INTERNAL VARIABLES


dec           = decimal.Decimal
ctx           = decimal.getcontext()
ctx.prec      = 50
DISPLAY_PREC  = 30
mpmath.mp.dps = 55
ISO_INLINE   = True
GUARD_DIGITS = 20
IMG          = True
NO_ASK       = False      # --no-ask / --pipe: never ask a question, fail instead
NO_LOOP      = False      # --no-loop / --pipe / --no-prompt: no 'x>' loop after an answer
_ERROR_COUNT = [0]        # error messages printed so far (decides the exit status of scripted runs)
_ERRORS_TO_STDERR = [False]


RED    = "\x1b[38;2;255;0;0m"
DRED    = "\x1b[38;2;104;0;0m"
DEL    = "\x1b[38;2;240;60;60m"      # removal confirmations; RED is reserved for errors
YELLOW = "\x1b[38;2;204;204;0m"
BRBL   = "\x1b[38;2;0;150;255m"
LSBL   = "\x1b[38;2;94;140;255m"
GREEN  = "\x1b[38;2;60;180;80m"
GRAY   = "\x1b[38;2;104;104;104m"
VIOLET = "\x1b[38;2;238;50;238m"
WHITE  = "\x1b[38;2;250;250;250m"
BOLD   = "\x1b[1m"
RST    = "\x1b[0m"
_NO_COLOR = bool(os.environ.get('NO_COLOR'))
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def _plain(text):
    return _ANSI_RE.sub('', text) if _NO_COLOR and isinstance(text, str) else text


def print(*args, **kwargs):
    if args and isinstance(args[0], str) and args[0].startswith(RED):      # an error message
        _ERROR_COUNT[0] += 1
        if _ERRORS_TO_STDERR[0] and 'file' not in kwargs:
            kwargs['file'] = sys.stderr
    builtins.print(*[_plain(a) for a in args], **kwargs)


def input(prompt=''):
    if NO_ASK:
        raise _AskDenied(prompt)
    return builtins.input(_plain(prompt))


_PY_JARGON = [
    (re.compile(r'\S*<locals>\S*\(\)'), 'the function'),
    (re.compile(r'\b(?:[A-Za-z_]\w*\.)+(\w+)\(\)'), r'\1()'),
    (re.compile(r'\b_+(\w+)\(\)'), r'\1()'),
    (re.compile(r"decimal\.Decimal|'mpf'|mpf object"), 'number'),
    (re.compile(r"'mpc'|mpc object|\bImgNum\b"), 'complex number'),
    (re.compile(r"\bSetObj\b"), 'set'), (re.compile(r"\bLambda\b"), 'function'), (re.compile(r"\b_Bool\b"), 'boolean'),
]


def _tidy_pyerror(msg: str) -> str:
    """Remove internal names and Python type jargon from an exception's text."""
    for pattern, repl in _PY_JARGON:
        msg = pattern.sub(repl, msg)
    return msg


class CalcError(Exception):
    """An expected, user-facing error: its message is printed as-is, without a traceback."""
    pass


class _AskDenied(CalcError):
    """Raised instead of asking a question while questions are off (--no-ask, --pipe)."""
    def __init__(self, prompt: str = ''):
        name = _ANSI_RE.sub('', prompt).strip().rstrip(':').strip()
        if not name or '[' in name:
            super().__init__(f"'{name}' has no value." if name else "A value is missing.")
            return
        nm = name if len(name) == 1 else f"_{name}_"
        super().__init__(f"'{name}' has no value. Give it one first: {nm}=5;<expression>, var {nm} 5, or --set {nm}=5")


def _fmt_error(msg: str) -> str:
    return f"{RED}{_unmangle(msg)}{RST}"


def _fmt_error_info(msg: str) -> str:
    return f"{DRED}{_unmangle(msg)}{RST}"


def _is_error_text(r: str) -> bool:
    return r.startswith(RED)


class Tok:
    """A token: type and text."""
    __slots__ = ('type', 'string')
    def __init__(self, type_: int, string: str):
        self.type   = type_
        self.string = string
    def __repr__(self):
        return f'Tok({self.type}, {self.string!r})'


_TOK_STRING = 200
_TOK_SFSTRING = 201


_user_vars:   dict  = {}
_const_vars:  dict  = {}
_last_lambda: list  = [None]
_inline_error: list = [None]
_pending_expr: list = [None]
_ABORT    = object()
_BACK     = object()
_UNDEF_RE = re.compile(r"'([^']+)' is not defined")


# NUMBER


class _DisplayDec(dec):
    """A Decimal printed in plain notation instead of scientific."""
    def __str__(self):
        if self.is_nan():      return 'nan'
        if self.is_infinite(): return 'inf' if self > 0 else '-inf'
        s, d, e = self.as_tuple()
        order = e + len(d) - 1
        if e < 0 and abs(order) < DISPLAY_PREC:
            return format(self, 'f')
        return super().__str__()
    def __repr__(self):
        return self.__str__()


class _Bool(dec):
    """Result of a comparison: numerically 1/0, displayed as True/False."""
    def __new__(cls, truth):
        return super().__new__(cls, 1 if truth else 0)
    def __str__(self):
        return 'True' if self != 0 else 'False'
    def __repr__(self):
        return self.__str__()


def _to_dec(v):
    return dec(mpmath.nstr(v, mpmath.mp.dps))


def _to_mpf(x, who=''):
    """Number -> mpmath value; mpf() cannot parse the text 'Infinity', so infinities and nan are mapped explicitly."""
    if isinstance(x, mpmath.mpc):
        return x
    if isinstance(x, dec):
        if x.is_nan():
            return mpmath.nan
        if x.is_infinite():
            return mpmath.inf if x > 0 else -mpmath.inf
    try:
        return mpmath.mpf(str(x))
    except (ValueError, TypeError):
        kind = ('set' if isinstance(x, SetObj) else 'function' if isinstance(x, Lambda) else 'string' if isinstance(x, str)
                else 'number with several imaginary units' if isinstance(x, ImgNum) else type(x).__name__)
        raise CalcError(f"{who}(): a number is needed, but got a {kind}." if who else f"A number is needed, but got a {kind}.")


def _error_text(r) -> str:
    """First line of an error result, without colors."""
    return _ANSI_RE.sub('', str(r)).strip().split('\n')[0]


def _lambda_to_callable(f, who=''):
    """A calculator function as a plain Python callable over mpmath numbers."""
    def call(*args):
        saved = ctx.prec
        ctx.prec = max(saved, int(mpmath.mp.prec * 0.30103) + 5)
        try:
            r = f(*args)
        finally:
            ctx.prec = saved
        if isinstance(r, _MissingArgs):
            raise CalcError(f"{who + '(): ' if who else ''}the function needs {len(f.params)} argument(s).")
        if isinstance(r, str):
            raise CalcError(f"{who + '(): ' if who else ''}{_error_text(r)}")
        return _to_mpf(r, who)
    return call


def _to_mp_arg(x, who=''):
    """Calculator value -> something mpmath accepts: function -> callable, finite set -> list, number -> mpf/mpc."""
    if isinstance(x, Lambda):
        return _lambda_to_callable(x, who)
    if isinstance(x, SetObj):
        if x.kind == 'ineq' or x.values is None:
            raise CalcError(f"{who + '(): ' if who else ''}a continuous set cannot be used as a list of numbers.")
        return [_to_mp_arg(SetObj._unwrap(v), who) for v in x.values]
    return _to_mpf(x, who)


def _from_mp_result(r):
    """mpmath result -> calculator value (lists become sets)."""
    if isinstance(r, mpmath.mpc):
        return r
    if isinstance(r, bool):
        return _Bool(r)
    if isinstance(r, (list, tuple)):
        return SetObj('list', values=[_from_mp_result(v) for v in r])
    if isinstance(r, mpmath.mpf) and r != 0 and mpmath.isfinite(r):
        bits = mpmath.mag(r)
        if bits < -3_300_000:
            return dec(0)
        if bits > 3_300_000:
            return dec('Infinity') if r > 0 else dec('-Infinity')
    return dec(str(r))


def _round_int(v):
    """The one rounding rule for whole numbers (used by round(), ~ and ~=): ties go to the even neighbour."""
    return v.to_integral_value(rounding=decimal.ROUND_HALF_EVEN)


def _op_pow(a, b):
    if isinstance(a, dec) and isinstance(b, dec):
        if b == 0:
            return dec(1)
        if a == 0 and b < 0:
            raise ZeroDivisionError('division by zero')
        if a < 0 and b.is_finite() and b != b.to_integral_value():
            return mpmath.power(_to_mpf(a), _to_mpf(b))
    return a ** b


def _op_truediv(a, b):
    if isinstance(a, dec) and isinstance(b, dec) and b == 0 and not a.is_nan():
        raise ZeroDivisionError('division by zero')
    return a / b


def _floor_divmod(a, b):
    """(floor(a/b), a - b*floor(a/b)) for finite Decimals, with the remainder taking the sign of b.
    A remainder within rounding noise of 0 or of b counts as an exact multiple, so that 100 // (1/6) is 600
    and 7 % (1/3) is 0 even though 1/6 and 1/3 are stored rounded."""
    q, r = a // b, a % b
    if q.is_nan() or r.is_nan():
        raise CalcError(f"The quotient has more than {ctx.prec} digits; // and % need it to fit the working precision.")
    if r != 0 and (r < 0) != (b < 0):
        q, r = q - 1, r + b
    tol = abs(a) * dec(10) ** -(ctx.prec - 6)
    if abs(r) <= tol:
        r = dec(0)
    elif 0 < abs(b - r) <= tol:
        q, r = q + 1, dec(0)
    return q, r


def _op_floordiv(a, b):
    """Floor division (rounds toward -inf, like Python) instead of Decimal's truncation."""
    if isinstance(a, dec) and isinstance(b, dec):
        if b == 0:
            raise ZeroDivisionError('division by zero')
        if a.is_finite() and b.is_finite():
            return _floor_divmod(a, b)[0]
    return a // b


def _op_mod(a, b):
    """Modulo whose result takes the sign of the divisor (like Python) instead of the dividend."""
    if isinstance(a, dec) and isinstance(b, dec):
        if b == 0:
            raise ZeroDivisionError('division by zero')
        if a.is_finite() and b.is_finite():
            return _floor_divmod(a, b)[1]
    return a % b


def _display(result: dec) -> dec:
    if result.is_infinite() or result.is_nan():
        return _DisplayDec(result)
    if result == 0:
        return _DisplayDec(0)

    sign, digits, exponent = result.as_tuple()
    num_digits = len(digits)
    order = exponent + num_digits - 1

    quantizer_exp = order - (DISPLAY_PREC - 1)
    try:
        rounded = result.quantize(dec(10) ** quantizer_exp, rounding=decimal.ROUND_HALF_EVEN)
    except (decimal.InvalidOperation, decimal.Overflow):
        rounded = result

    if rounded == 0:
        return _DisplayDec(0)

    normalized = rounded.normalize()
    sign2, digits2, exponent2 = normalized.as_tuple()
    order2 = exponent2 + len(digits2) - 1

    if exponent2 >= 0 and abs(order2) < DISPLAY_PREC:
        return _DisplayDec(int(normalized))

    return _DisplayDec(normalized)


def _display_complex(result: mpmath.mpc) -> str:
    unit    = _disp_name(_UNIT_KEYS[_ACTIVE_UNITS[0]]) if _ACTIVE_UNITS else 'i'
    re_part = _display(dec(mpmath.nstr(result.real, mpmath.mp.dps)))
    im_raw  = dec(mpmath.nstr(result.imag, mpmath.mp.dps))
    im      = _display(abs(im_raw))
    im_str  = '' if im == 1 else str(im)
    if re_part == 0:
        return f"-{im_str}{unit}" if im_raw < 0 else f"{im_str}{unit}"
    sign = '-' if im_raw < 0 else '+'
    return f"{re_part}{sign}{im_str}{unit}"


# Imaginary units. The first is "i"; `img <name>` switches more on. Every unit squares to -1 and units
# commute, so 1+2i+3j is one number with two independent imaginary parts (and i*j is a third part,
# which squares to +1). The first active unit (the primary one) is an ordinary mpmath complex number,
# so everything mpmath can do keeps working with it. A number that also uses another unit is an ImgNum.

_UNIT_KEYS:    list = ['i']      # unit id -> internal name (a letter, or the mangled _long_name_); ids are never reused
_UNIT_LIST:    list = [0]        # ids of the units you have, in the order shown by `img`
_UNIT_OFF:     set  = set()      # ids of the listed units that are switched off
_ACTIVE_UNITS: list = [0]        # ids of the units that are on, in list order; the first is the main one


def _unit_id(key: str) -> int:
    if key not in _UNIT_KEYS:
        _UNIT_KEYS.append(key)
    return _UNIT_KEYS.index(key)


def _unit_active_key(key: str) -> bool:
    return key in _UNIT_KEYS and _UNIT_KEYS.index(key) in _ACTIVE_UNITS


def _mask_bits(mask: int) -> list:
    return [k for k in range(mask.bit_length()) if mask >> k & 1]


def _primary_bit():
    return (1 << _ACTIVE_UNITS[0]) if _ACTIVE_UNITS else None


def _img_parts(v):
    """Number -> {unit-product mask: Decimal coefficient} (mask 0 is the real part), or None if v is no number."""
    if isinstance(v, ImgNum):
        return v.p
    if isinstance(v, mpmath.mpc):
        out = {}
        re_, im_ = _to_dec(v.real), _to_dec(v.imag)
        if re_ != 0: out[0] = re_
        if im_ != 0: out[_primary_bit() or 1] = im_
        return out
    if isinstance(v, mpmath.mpf):
        v = _to_dec(v)
    if isinstance(v, (dec, int)) and not isinstance(v, bool):
        c = dec(v)
        return {0: c} if c != 0 else {}
    return None


def _img_norm(p: dict):
    """Parts -> the simplest value: a Decimal, a primary-unit complex number, or an ImgNum."""
    p = {m: c for m, c in p.items() if c != 0}
    pb = _primary_bit()
    if all(m == 0 or m == pb for m in p):
        im_ = p.get(pb, dec(0)) if pb else dec(0)
        if im_ == 0:
            return p.get(0, dec(0))
        return mpmath.mpc(_to_mpf(p.get(0, dec(0))), _to_mpf(im_))
    return ImgNum(p)


def _img_clean(v):
    """Drop coefficients that are only rounding noise."""
    tol = dec(10) ** -(ctx.prec - 2)
    return _img_norm({m: c for m, c in v.p.items() if abs(c) >= tol})


def _img_mul_parts(pa: dict, pb: dict) -> dict:
    out = {}
    for m1, c1 in pa.items():
        for m2, c2 in pb.items():
            t = c1 * c2
            if bin(m1 & m2).count('1') & 1:
                t = -t
            out[m1 ^ m2] = out.get(m1 ^ m2, dec(0)) + t
    return out


def _img_div(pa: dict, pb: dict) -> dict:
    """pa / pb as parts: solves pb * x = pa."""
    if not pb:
        raise ZeroDivisionError('division by zero')
    if set(pb) == {0}:
        return {m: c / pb[0] for m, c in pa.items()}
    imag = set(pb) - {0}
    if len(imag) == 1 and bin(next(iter(imag))).count('1') == 1:
        u = next(iter(imag))
        x, y = pb.get(0, dec(0)), pb[u]
        d = x * x + y * y
        return _img_mul_parts(pa, {0: x / d, u: -y / d})
    bits = sorted({k for m in list(pa) + list(pb) for k in _mask_bits(m)})
    pos  = {k: j for j, k in enumerate(bits)}
    def dense(m):
        return sum(1 << pos[k] for k in _mask_bits(m))
    size = 1 << len(bits)
    mat  = [[dec(0)] * size for _ in range(size)]
    for e in range(size):
        for m, c in pb.items():
            dm = dense(m)
            mat[dm ^ e][e] += -c if bin(dm & e).count('1') & 1 else c
    rhs = [dec(0)] * size
    for m, c in pa.items():
        rhs[dense(m)] = c
    tol = max(abs(c) for c in pb.values()) * dec(10) ** -(ctx.prec - 8)
    for col in range(size):
        piv = max(range(col, size), key=lambda r: abs(mat[r][col]))
        if abs(mat[piv][col]) <= tol:
            raise CalcError("This number has no inverse (its imaginary units multiply to zero).")
        mat[col], mat[piv] = mat[piv], mat[col]
        rhs[col], rhs[piv] = rhs[piv], rhs[col]
        for r in range(col + 1, size):
            f = mat[r][col] / mat[col][col]
            if f:
                for cc in range(col, size):
                    mat[r][cc] -= f * mat[col][cc]
                rhs[r] -= f * rhs[col]
    x = [dec(0)] * size
    for r in range(size - 1, -1, -1):
        x[r] = (rhs[r] - sum((mat[r][cc] * x[cc] for cc in range(r + 1, size)), dec(0))) / mat[r][r]
    out = {}
    for idx, v in enumerate(x):
        if v != 0:
            out[sum(1 << bits[j] for j in range(len(bits)) if idx >> j & 1)] = v
    return out


def _img_via_unit(call, args, who=''):
    """Run call on mpmath numbers: a + b*u (u any single unit) behaves like the ordinary complex number a + b*i,
    so any function works for it. Several different units in one call cannot be mapped that way."""
    units = set()
    for a in args:
        if isinstance(a, ImgNum):
            for m in a.p:
                units.update(_mask_bits(m))
        elif isinstance(a, mpmath.mpc) and a.imag != 0:
            units.add((_primary_bit() or 1).bit_length() - 1)
    if len(units) > 1:
        names = ', '.join(_disp_name(_UNIT_KEYS[u]) for u in sorted(units))
        raise CalcError(f"{who + '(): ' if who else ''}works with one imaginary unit at a time, but got {names} together "
                        f"(+ - * / and whole-number powers work with any mix).")
    u = next(iter(units))
    conv = [mpmath.mpc(_to_mpf(a.p.get(0, dec(0))), _to_mpf(a.p.get(1 << u, dec(0)))) if isinstance(a, ImgNum) else a
            for a in args]
    r = call(*conv)
    if isinstance(r, mpmath.mpc):
        return _img_norm({0: _to_dec(r.real), 1 << u: _to_dec(r.imag)})
    return r


def _mp_power(b, e):
    return _from_mp_result(mpmath.power(_to_mpf(b), _to_mpf(e)))


def _img_pow(a, e):
    if isinstance(e, (dec, int)) and not isinstance(e, bool):
        ed = dec(e)
        if ed.is_finite() and ed == ed.to_integral_value():
            n = int(ed)
            if n == 0:
                return dec(1)
            result, base, k = {0: dec(1)}, dict(a.p), abs(n)
            while k:
                if k & 1:
                    result = _img_mul_parts(result, base)
                k >>= 1
                if k:
                    base = _img_mul_parts(base, base)
            if n < 0:
                result = _img_div({0: dec(1)}, result)
            return _img_norm(result)
    return _img_via_unit(_mp_power, (a, e), 'power')


def _img_add(a, b, sign):
    pa, pb = _img_parts(a), _img_parts(b)
    if pa is None or pb is None:
        return NotImplemented
    out = dict(pa)
    for m, c in pb.items():
        out[m] = out.get(m, dec(0)) + sign * c
    return _img_norm(out)


class ImgNum:
    """A number that uses an imaginary unit other than the primary one (see `img`)."""
    __slots__ = ('p',)

    def __init__(self, p: dict):
        self.p = p

    def __add__(self, o):  return _img_add(self, o, 1)
    def __radd__(self, o): return _img_add(self, o, 1)
    def __sub__(self, o):  return _img_add(self, o, -1)
    def __rsub__(self, o): return _img_add(o, self, -1)

    def __mul__(self, o):
        po = _img_parts(o)
        return NotImplemented if po is None else _img_norm(_img_mul_parts(self.p, po))
    __rmul__ = __mul__

    def __truediv__(self, o):
        po = _img_parts(o)
        return NotImplemented if po is None else _img_norm(_img_div(self.p, po))
    def __rtruediv__(self, o):
        po = _img_parts(o)
        return NotImplemented if po is None else _img_norm(_img_div(po, self.p))

    def __pow__(self, e):  return _img_pow(self, e)
    def __rpow__(self, b): return _img_via_unit(_mp_power, (b, self), 'power')

    def __neg__(self):     return ImgNum({m: -c for m, c in self.p.items()})
    def __pos__(self):     return self
    def __abs__(self):     return _abs(self)

    def __eq__(self, o):
        po = _img_parts(o)
        return NotImplemented if po is None else {m: c for m, c in po.items() if c != 0} == self.p
    def __hash__(self):    return hash(frozenset(self.p.items()))
    def __str__(self):     return _display_imgnum(self)
    __repr__ = __str__


_CPLX = (mpmath.mpc, ImgNum)


def _display_imgnum(v: ImgNum) -> str:
    out = ''
    for m, c in sorted(v.p.items(), key=lambda kv: (bin(kv[0]).count('1'), kv[0])):
        mag = _display(abs(c))
        if m:
            names = [_disp_name(_UNIT_KEYS[k]) for k in _mask_bits(m)]
            label = ('*' if any(len(n) > 1 for n in names) else '').join(names)
            body  = label if mag == 1 else f"{mag}{label}"
        else:
            body = str(mag)
        out += ('-' if c < 0 else '+' if out else '') + body
    return out


def _truthy(v):
    if isinstance(v, mpmath.mpc):  return v != 0
    if isinstance(v, ImgNum):      return True
    if isinstance(v, dec):         return v != 0
    if isinstance(v, str):         return len(v) > 0
    if isinstance(v, Lambda):      return bool(v.expr.strip())
    if isinstance(v, SetObj):
        if v.kind == 'zeros2d':    return bool(v.rows and v.cols)
        if v.kind == 'ineq':       return bool(v.clauses)
        return bool(v.values or v.overrides or v.modificators)
    return bool(v)


def _not(v):
    return _Bool(not _truthy(v))


def _all_true(*conds):
    return all(_truthy(c) for c in conds)


def _approx_eq(a, b):
    """a ~= b : both sides rounded to the nearest integer, then compared."""
    def rnd(v):
        if isinstance(v, ImgNum):
            return tuple(sorted((m, rnd(c)) for m, c in v.p.items()))
        if isinstance(v, mpmath.mpc):
            return (rnd(dec(mpmath.nstr(v.real, mpmath.mp.dps))), rnd(dec(mpmath.nstr(v.imag, mpmath.mp.dps))))
        if isinstance(v, dec):
            if v.is_infinite() or v.is_nan(): return v
            return _round_int(v)
        return v
    return _Bool(rnd(a) == rnd(b))


# VARIABLE


_lv_to_mangled = {}
_mangled_to_lv = {}


def _register_longvar(inner: str) -> str:
    if inner not in _lv_to_mangled:
        n   = len(_lv_to_mangled)
        m   = f"XLONGx{n}x"
        _lv_to_mangled[inner] = m
        _mangled_to_lv[m]     = inner
    return _lv_to_mangled[inner]


def _is_longvar(s: str) -> bool:
    return s in _mangled_to_lv


def _longvar_inner(s: str) -> str:
    return _mangled_to_lv.get(s, s)


def _preprocess_lv(s: str) -> str:
    buf = []
    i = 0
    while i < len(s):
        if s[i] == '_':
            j = s.find('_', i + 1)
            if j > i:
                buf.append(_register_longvar(s[i+1:j]))
                i = j + 1
            else:
                buf.append('_')
                i += 1
        else:
            buf.append(s[i])
            i += 1
    return re.sub(r'(XLONGx\d+x)(\d)', r'\1*\2', ''.join(buf))


def _split_alnum(s: str) -> list:
    raw_segs = []
    i = 0
    while i < len(s):
        if s[i].isdigit():
            j = i
            while j < len(s) and s[j].isdigit():
                j += 1
            raw_segs.append((tokenize.NUMBER, s[i:j]))
            i = j
        else:
            j = i
            while j < len(s) and not s[j].isdigit():
                j += 1
            raw_segs.append(('LETTERS', s[i:j]))
            i = j

    result = []
    for kind, val in raw_segs:
        if kind == tokenize.NUMBER:
            result.append(Tok(tokenize.NUMBER, val))
        elif _is_longvar(val):
            result.append(Tok(tokenize.NAME, val))
        else:
            result.extend(_greedy_name(val))
    return result


def _greedy_name(s: str) -> list:
    result = []
    i = 0
    while i < len(s):
        matched = False
        for length in range(len(s) - i, 1, -1):
            candidate = s[i:i+length]
            if candidate in dco:
                result.append(Tok(tokenize.NAME, candidate))
                i += length
                matched = True
                break
        if not matched:
            result.append(Tok(tokenize.NAME, s[i]))
            i += 1
    return result


def _should_split(name: str) -> bool:
    if not any(c.isdigit() for c in name):
        return False
    if name not in dco or not callable(dco[name]):
        return False
    i = 0
    while i < len(name) and not name[i].isdigit():
        i += 1
    letter_part = name[:i]
    if not letter_part:
        return False
    toks = _greedy_name(letter_part)
    return all(t.string in dco and not callable(dco[t.string]) for t in toks)


def _fmt_sub_key(base: str, key) -> str:
    if isinstance(key, (dec, _DisplayDec)):
        return f"{base}[{int(key) if key == key.to_integral_value() else key}]"
    if isinstance(key, str):
        return f'{base}[{key}]'
    return f"{base}[{key}]"


class SubProxy:
    """Stands in for a subscripted name: `x[1]` reads the variable 'x[1]'."""
    __slots__ = ('name', 'env', '_orig')
    def __init__(self, name: str, env: dict, orig=None):
        self.name  = name
        self.env   = env
        self._orig = orig
    def __getitem__(self, key):
        if isinstance(key, SubProxy): key = key._orig
        k = _fmt_sub_key(self.name, key)
        if k in self.env: return self.env[k]
        raise NameError(f"'{k}' is not defined")
    def __repr__(self):
        return repr(self._orig) if self._orig is not None else f"SubProxy({self.name!r})"
    def __add__(self, o):      return self._orig + o  if self._orig is not None else NotImplemented
    def __radd__(self, o):     return o + self._orig  if self._orig is not None else NotImplemented
    def __sub__(self, o):      return self._orig - o  if self._orig is not None else NotImplemented
    def __rsub__(self, o):     return o - self._orig  if self._orig is not None else NotImplemented
    def __mul__(self, o):      return self._orig * o  if self._orig is not None else NotImplemented
    def __rmul__(self, o):     return o * self._orig  if self._orig is not None else NotImplemented
    def __truediv__(self, o):  return self._orig / o  if self._orig is not None else NotImplemented
    def __rtruediv__(self, o): return o / self._orig  if self._orig is not None else NotImplemented
    def __pow__(self, o):      return self._orig ** o if self._orig is not None else NotImplemented
    def __rpow__(self, o):     return o ** self._orig if self._orig is not None else NotImplemented
    def __neg__(self):         return -self._orig     if self._orig is not None else NotImplemented
    def __pos__(self):         return +self._orig     if self._orig is not None else NotImplemented
    def __abs__(self):         return abs(self._orig) if self._orig is not None else NotImplemented
    def __eq__(self, o):       return self._orig == o if self._orig is not None else NotImplemented
    def __lt__(self, o):       return self._orig < o  if self._orig is not None else NotImplemented
    def __le__(self, o):       return self._orig <= o if self._orig is not None else NotImplemented
    def __gt__(self, o):       return self._orig > o  if self._orig is not None else NotImplemented
    def __ge__(self, o):       return self._orig >= o if self._orig is not None else NotImplemented


def get_sub_specs(s: str) -> list:
    specs  = []
    seen   = set()
    tokens = get_clean_tokens(s)
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if (t.type == tokenize.NAME and t.string not in dco and
                i + 1 < len(tokens) and
                tokens[i+1].type == tokenize.OP and
                tokens[i+1].string == '['):
            j = i + 2
            depth = 1
            while j < len(tokens):
                if   tokens[j].string == '[': depth += 1
                elif tokens[j].string == ']':
                    depth -= 1
                    if depth == 0: break
                j += 1
            index_toks = tokens[i+2:j]
            index_expr = ''.join(tk.string for tk in index_toks)
            key = (t.string, index_expr)
            if key not in seen:
                specs.append((t.string, index_expr))
                seen.add(key)
            i = j + 1
            continue
        i += 1
    return specs


def _normalize_sub_key(key: str) -> str:
    m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\[(XSFSTRx\d+x)\]$', key)
    if m and _is_sfstr(m.group(2)):
        return f'{m.group(1)}[{_sfstr_inner(m.group(2))}]'
    return key


def _scan_vars(tokens: list, lo: int, hi: int, found: set, seen: list):
    i = lo
    while i < hi:
        t = tokens[i]
        if t.type == tokenize.NAME and i + 1 < hi and tokens[i+1].string == '[':
            j = i + 2
            depth = 1
            while j < hi:
                if   tokens[j].string == '[': depth += 1
                elif tokens[j].string == ']':
                    depth -= 1
                    if depth == 0: break
                j += 1
            _scan_vars(tokens, i + 2, j, found, seen)
            i = j + 1
            continue
        if t.string == '[':
            prev = tokens[i-1] if i > lo else None
            is_subscript = prev is not None and prev.string in (')', ']', '}')
            j = i + 1
            depth = 1
            while j < hi:
                if   tokens[j].string == '[': depth += 1
                elif tokens[j].string == ']':
                    depth -= 1
                    if depth == 0: break
                j += 1
            if is_subscript:
                _scan_vars(tokens, i + 1, j, found, seen)
            i = j + 1
            continue
        if t.type == tokenize.NAME:
            if (len(t.string) == 1 and t.string not in dco) or (_is_longvar(t.string) and t.string not in dco):
                if t.string not in found:
                    found.add(t.string); seen.append(t.string)
        i += 1


def getv(s: str) -> list:
    seen = []
    found = set()
    tokens = get_clean_tokens(s)
    _scan_vars(tokens, 0, len(tokens), found, seen)
    return seen


def _is_subscript_target(name: str) -> bool:
    """'x[3]' or 'x[<string key>]' (the key already mangled by _strip_spaces)."""
    return bool(re.match(r'^[A-Za-z_][A-Za-z0-9_]*\[(?:\d+|XSFSTRx\d+x)\]$', name))


def _is_assign_target(lhs: str) -> bool:
    return ((len(lhs) == 1 and lhs.isalpha()) or
            _is_longvar(lhs) or
            _is_subscript_target(lhs))


_SET_INDEX_TGT_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\[(.+)\]$')


def _stored() -> dict:
    """Everything remembered between lines: variables and constants (a name is never in both)."""
    return {**_user_vars, **_const_vars}


def _persist(key, value) -> None:
    """Remember key across evaluations unless it is a protected constant."""
    if key not in _const_vars:
        _user_vars[key] = value


def _store_assignment(work: dict, tgt: str, ev) -> None:
    """Store ev under tgt in work. 'name[idx]' extends the set held by name
    (see item: set index assignment); anything else is a plain variable."""
    m = _SET_INDEX_TGT_RE.match(tgt)
    if m and isinstance(work.get(m.group(1)), SetObj):
        old, key_txt = work[m.group(1)], m.group(2)
        key = dec(key_txt) if re.match(r'^-?\d+$', key_txt) else key_txt
        new = old.copy(overrides={**old.overrides, key: ev})
        work[m.group(1)] = new; _persist(m.group(1), new)
        return
    work[tgt] = ev
    if isinstance(ev, (Lambda, SetObj)):
        _persist(tgt, ev)


# LAMBDA


class _MissingArgs:
    """Result of calling a function with too few arguments."""
    __slots__ = ('lam', 'provided', 'missing')
    def __init__(self, lam, provided: tuple, missing: list):
        self.lam      = lam
        self.provided = provided
        self.missing  = missing
    def __repr__(self):
        names = ', '.join(_longvar_inner(p) if _is_longvar(p) else p for p in self.missing)
        return f"{RED}Invalid syntax: missing argument(s): {names}{RST}"
    def __str__(self):
        return self.__repr__()


def _scan_lambda_params(tokens: list, lo: int, hi: int, found: set, seen: list):
    i = lo
    while i < hi:
        t = tokens[i]
        if t.type == tokenize.NAME and i + 1 < hi and tokens[i+1].string == '[':
            j = i + 2
            depth = 1
            while j < hi:
                if   tokens[j].string == '[': depth += 1
                elif tokens[j].string == ']':
                    depth -= 1
                    if depth == 0: break
                j += 1
            idx_toks = tokens[i+2:j]
            _scan_lambda_params(tokens, i + 2, j, found, seen)
            if len(idx_toks) == 1 and idx_toks[0].type == tokenize.NUMBER:
                k = f"{t.string}[{idx_toks[0].string}]"
                if k not in found:
                    found.add(k); seen.append(k)
            i = j + 1
            continue
        if t.string == '[':
            prev = tokens[i-1] if i > lo else None
            is_subscript = prev is not None and prev.string in (')', ']', '}')
            j = i + 1
            depth = 1
            while j < hi:
                if   tokens[j].string == '[': depth += 1
                elif tokens[j].string == ']':
                    depth -= 1
                    if depth == 0: break
                j += 1
            if is_subscript:
                _scan_lambda_params(tokens, i + 1, j, found, seen)
            i = j + 1
            continue
        if t.type == tokenize.NAME:
            if (len(t.string) == 1 and t.string not in dco) or (_is_longvar(t.string) and t.string not in dco):
                if t.string not in found:
                    found.add(t.string); seen.append(t.string)
        i += 1


def _get_lambda_params(expr: str) -> list:
    seen = []
    found = set()
    tokens = get_clean_tokens(expr)
    _scan_lambda_params(tokens, 0, len(tokens), found, seen)
    return seen


class Lambda:
    """A stored expression such as "x**2"."""
    def __init__(self, expr: str, params: list = None):
        self.expr   = expr
        self.params = list(params) if params is not None else _get_lambda_params(expr)

    def __eq__(self, o):
        if not isinstance(o, Lambda): return NotImplemented
        return self.expr == o.expr and self.params == o.params
    def __ne__(self, o):
        r = self.__eq__(o)
        return r if r is NotImplemented else not r
    def __hash__(self):
        return hash((self.expr, tuple(self.params)))

    def __call__(self, *args):
        if self.params and len(args) < len(self.params):
            return _MissingArgs(self, args, self.params[len(args):])
        v = {}
        for name, val in zip(self.params, args):
            if isinstance(val, dec):
                v[name] = val
            elif isinstance(val, mpmath.mpf):
                v[name] = dec(mpmath.nstr(val, ctx.prec + 5))
            elif isinstance(val, (int, float)):
                v[name] = dec(str(val))
            else:
                v[name] = val
        return cal(self.expr, v, nodisplay=True)

    def _arith(self, other, op: str, flipped: bool = False):
        if isinstance(other, Lambda):
            params = list(self.params)
            for p in other.params:
                if p not in params:
                    params.append(p)
            a, b = (other.expr, self.expr) if flipped else (self.expr, other.expr)
            return Lambda(f"({a}) {op} ({b})", params)
        if isinstance(other, dec):
            if flipped:
                return Lambda(f"{other} {op} ({self.expr})", self.params)
            return Lambda(f"({self.expr}) {op} {other}", self.params)
        return NotImplemented

    def __add__(self, o):      return self._arith(o, '+')
    def __radd__(self, o):     return self._arith(o, '+', True)
    def __sub__(self, o):      return self._arith(o, '-')
    def __rsub__(self, o):     return self._arith(o, '-', True)
    def __mul__(self, o):      return self._arith(o, '*')
    def __rmul__(self, o):     return self._arith(o, '*', True)
    def __truediv__(self, o):  return self._arith(o, '/')
    def __rtruediv__(self, o): return self._arith(o, '/', True)
    def __floordiv__(self, o):  return self._arith(o, '//')
    def __rfloordiv__(self, o): return self._arith(o, '//', True)
    def __pow__(self, o):      return self._arith(o, '**')
    def __rpow__(self, o):     return self._arith(o, '**', True)
    def __neg__(self):         return Lambda(f"-({self.expr})", self.params)
    def __pos__(self):         return Lambda(self.expr, self.params)

    def __repr__(self):
        shown = _unmangle(self.expr)
        return f'"{shown}"'
    def __str__(self):
        return self.__repr__()


def _run_lambda(*args):
    if args and isinstance(args[0], Lambda):
        f, vals = args[0], args[1:]
    else:
        f, vals = _last_lambda[0], args
    if not isinstance(f, Lambda):
        raise CalcError("run() expects a Lambda as first argument, or a prior "
                          "unassigned Lambda result to reuse. Example: run(f, 2, 3)")
    if not f.params:
        return f()
    if not vals:
        raise CalcError(f"run() missing argument(s) for: {', '.join(f.params)}")
    call_args = [vals[i % len(vals)] for i in range(len(f.params))]
    return f(*call_args)


class _Lit(float):
    """A number inside a symbolic expression: keeps its exact decimal value and prints as it was written."""
    def __new__(cls, d):
        obj = super().__new__(cls, float(d))
        obj.d = d
        return obj

    def __repr__(self):
        d = self.d
        return str(int(d)) if d == d.to_integral_value() else format(d.normalize(), 'f')


def _cv(node):
    """The exact Decimal value of a numeric Constant node, else None."""
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, _Lit):
            return v.d
        if isinstance(v, int) and not isinstance(v, bool):
            return dec(v)
        if isinstance(v, float):
            return dec(repr(v))
    return None


def _lit(d):
    return ast.Constant(value=_Lit(d))


def _fold(a, op, b):
    """Exact constant folding; None when the result would not be exact (1/3 stays symbolic) or is undefined."""
    try:
        if isinstance(op, ast.Add):  return a + b
        if isinstance(op, ast.Sub):  return a - b
        if isinstance(op, ast.Mult): return a * b
        if isinstance(op, ast.Div):
            if b == 0:
                return None
            q = a / b
            with decimal.localcontext() as lc:
                lc.prec = 4 * ctx.prec + 20
                return q if q * b == a else None
        if isinstance(op, ast.Pow):
            if b == b.to_integral_value() and 0 <= b <= 1000:
                return a ** int(b)
    except Exception:
        pass
    return None


def _ratio(a, b):
    """a / b as an exact constant node: a reduced fraction for integers, e.g. 6/9 -> 2 / 3."""
    if a == a.to_integral_value() and b == b.to_integral_value():
        import math
        g = math.gcd(int(a), int(b)) * (-1 if b < 0 else 1)
        p_, q_ = int(a) // g, int(b) // g
        return _lit(dec(p_)) if q_ == 1 else ast.BinOp(_lit(dec(p_)), ast.Div(), _lit(dec(q_)))
    folded = _fold(a, ast.Div(), b)
    return _lit(folded) if folded is not None else ast.BinOp(_lit(a), ast.Div(), _lit(b))


def _simp(node):
    if isinstance(node, ast.BinOp):
        L, R = _simp(node.left), _simp(node.right)
        op   = node.op
        lv, rv = _cv(L), _cv(R)
        lz, rz = lv is not None and lv == 0, rv is not None and rv == 0
        lo, ro = lv is not None and lv == 1, rv is not None and rv == 1

        if isinstance(op, ast.Add):
            if lz: return R
            if rz: return L
        elif isinstance(op, ast.Sub):
            if rz: return L
            if lz: return _simp(ast.UnaryOp(ast.USub(), R))
            if ast.dump(L) == ast.dump(R): return ast.Constant(value=0)
        elif isinstance(op, ast.Mult):
            if lz or rz: return ast.Constant(value=0)
            if lo: return R
            if ro: return L
        elif isinstance(op, ast.Div):
            if lz: return ast.Constant(value=0)
            if ro: return L
            if ast.dump(L) == ast.dump(R): return ast.Constant(value=1)
            if lv is not None and rv is not None and rv != 0 and _fold(lv, op, rv) is None:
                return _ratio(lv, rv)
            if rv is not None and rv != 0 and isinstance(L, ast.BinOp) and isinstance(L.op, ast.Mult):
                for k, rest in ((L.left, L.right), (L.right, L.left)):
                    kv = _cv(k)
                    if kv is not None:
                        return ast.BinOp(_ratio(kv, rv), ast.Mult(), rest)
        elif isinstance(op, ast.Pow):
            if rz: return ast.Constant(value=1)
            if ro: return L
            if lz: return ast.Constant(value=0)

        if lv is not None and rv is not None:
            folded = _fold(lv, op, rv)
            if folded is not None:
                return _lit(folded)

        if isinstance(op, ast.Mult):
            for c, other in ((L, R), (R, L)):
                cv = _cv(c)
                if cv is not None and isinstance(other, ast.BinOp) and isinstance(other.op, ast.Mult):
                    for k, rest in ((other.left, other.right), (other.right, other.left)):
                        kv = _cv(k)
                        if kv is not None:
                            return _simp(ast.BinOp(_lit(cv * kv), ast.Mult(), rest))

        node.left, node.right = L, R
        return node

    elif isinstance(node, ast.UnaryOp):
        op = _simp(node.operand)
        if isinstance(node.op, ast.USub):
            v = _cv(op)
            if v is not None:
                return _lit(-v)
            if isinstance(op, ast.UnaryOp) and isinstance(op.op, ast.USub):
                return op.operand
        elif isinstance(node.op, ast.UAdd):
            return op
        node.operand = op
        return node

    elif isinstance(node, ast.Call):
        node.args = [_simp(a) for a in node.args]
        return node

    return node


def _C(name, *args):
    return ast.Call(ast.Name(name, ast.Load()), list(args), [])


def _depends_on(node, var: str) -> bool:
    return any(isinstance(n, ast.Name) and n.id == var for n in ast.walk(node))


def _diff_node(node, var: str):
    if isinstance(node, ast.Constant):
        return ast.Constant(value=0)

    if isinstance(node, ast.Name):
        return ast.Constant(value=1 if node.id == var else 0)

    if isinstance(node, ast.UnaryOp):
        d = _diff_node(node.operand, var)
        if isinstance(node.op, ast.USub):
            return _simp(ast.UnaryOp(ast.USub(), d))
        return d

    if isinstance(node, ast.BinOp):
        L, R   = node.left, node.right
        dL, dR = _diff_node(L, var), _diff_node(R, var)
        op     = node.op

        if isinstance(op, (ast.Add, ast.Sub)):
            return _simp(ast.BinOp(dL, op, dR))

        if isinstance(op, ast.Mult):
            return _simp(ast.BinOp(
                ast.BinOp(dL, ast.Mult(), R),
                ast.Add(),
                ast.BinOp(L, ast.Mult(), dR)))

        if isinstance(op, ast.Div):
            return _simp(ast.BinOp(
                ast.BinOp(
                    ast.BinOp(dL, ast.Mult(), R),
                    ast.Sub(),
                    ast.BinOp(L, ast.Mult(), dR)),
                ast.Div(),
                ast.BinOp(R, ast.Pow(), ast.Constant(value=2))))

        if isinstance(op, ast.Pow):
            dR_s = _simp(dR)
            if isinstance(dR_s, ast.Constant) and dR_s.value == 0:

                return _simp(ast.BinOp(
                    ast.BinOp(R, ast.Mult(),
                        ast.BinOp(L, ast.Pow(),
                            _simp(ast.BinOp(R, ast.Sub(), ast.Constant(value=1))))),
                    ast.Mult(), _simp(dL)))

            dL_s = _simp(dL)
            inner = _simp(ast.BinOp(
                ast.BinOp(dR_s, ast.Mult(), _C('log', L)),
                ast.Add(),
                ast.BinOp(ast.BinOp(R, ast.Mult(), dL_s), ast.Div(), L)))
            return _simp(ast.BinOp(node, ast.Mult(), inner))

    if isinstance(node, ast.Call):
        fn = node.func.id if isinstance(node.func, ast.Name) else None
        if not any(_depends_on(a, var) for a in node.args):
            return ast.Constant(value=0)
        if fn == 'log' and len(node.args) == 2 and not _depends_on(node.args[1], var):
            f, base = node.args
            df = _simp(_diff_node(f, var))
            return _simp(ast.BinOp(df, ast.Div(), ast.BinOp(f, ast.Mult(), _C('log', base))))
        if fn and len(node.args) == 1:
            f  = node.args[0]
            df = _simp(_diff_node(f, var))
            if _cv(df) == 0:
                return ast.Constant(value=0)
            one_df = isinstance(df, ast.Constant) and df.value == 1

            def chain(d_out):
                return _simp(d_out if one_df else
                             ast.BinOp(d_out, ast.Mult(), df))

            sq   = lambda e: ast.BinOp(e, ast.Pow(), ast.Constant(value=2))
            inv  = lambda e: ast.BinOp(ast.Constant(value=1), ast.Div(), e)
            neg  = lambda e: ast.UnaryOp(ast.USub(), e)
            one  = ast.Constant(value=1)
            rule = {
                'sin':   lambda: chain(_C('cos', f)),
                'cos':   lambda: chain(neg(_C('sin', f))),
                'tan':   lambda: chain(inv(sq(_C('cos', f)))),
                'cot':   lambda: chain(neg(inv(sq(_C('sin', f))))),
                'sec':   lambda: chain(ast.BinOp(_C('sec', f), ast.Mult(), _C('tan', f))),
                'csc':   lambda: chain(neg(ast.BinOp(_C('csc', f), ast.Mult(), _C('cot', f)))),
                'exp':   lambda: chain(_C('exp', f)),
                'log':   lambda: chain(inv(f)),
                'ln':    lambda: chain(inv(f)),
                'sqrt':  lambda: chain(inv(ast.BinOp(
                             ast.Constant(value=2), ast.Mult(), _C('sqrt', f)))),
                'cbrt':  lambda: chain(inv(ast.BinOp(
                             ast.Constant(value=3), ast.Mult(), sq(_C('cbrt', f))))),
                'abs':   lambda: chain(_C('sign', f)),
                'asin':  lambda: chain(inv(_C('sqrt', ast.BinOp(one, ast.Sub(), sq(f))))),
                'acos':  lambda: chain(neg(inv(_C('sqrt', ast.BinOp(one, ast.Sub(), sq(f)))))),
                'atan':  lambda: chain(inv(ast.BinOp(one, ast.Add(), sq(f)))),
                'sinh':  lambda: chain(_C('cosh', f)),
                'cosh':  lambda: chain(_C('sinh', f)),
                'tanh':  lambda: chain(inv(sq(_C('cosh', f)))),
                'asinh': lambda: chain(inv(_C('sqrt', ast.BinOp(sq(f), ast.Add(), one)))),
                'acosh': lambda: chain(inv(_C('sqrt', ast.BinOp(sq(f), ast.Sub(), one)))),
                'atanh': lambda: chain(inv(ast.BinOp(one, ast.Sub(), sq(f)))),
                'erf':   lambda: chain(ast.BinOp(ast.BinOp(ast.Constant(value=2), ast.Div(), _C('sqrt', ast.Name('pi', ast.Load()))),
                                                 ast.Mult(), _C('exp', neg(sq(f))))),
                'erfc':  lambda: chain(neg(ast.BinOp(ast.BinOp(ast.Constant(value=2), ast.Div(), _C('sqrt', ast.Name('pi', ast.Load()))),
                                                     ast.Mult(), _C('exp', neg(sq(f)))))),
                'gamma': lambda: chain(ast.BinOp(_C('gamma', f), ast.Mult(), _C('digamma', f))),
                'log10': lambda: chain(inv(ast.BinOp(f, ast.Mult(),
                             _C('log', ast.Constant(value=10))))),
                'log2':  lambda: chain(inv(ast.BinOp(f, ast.Mult(),
                             _C('log', ast.Constant(value=2))))),
            }
            if fn in rule:
                return rule[fn]()
        raise CalcError(f"diff(): don't know the derivative of {ast.unparse(node)}.")

    if isinstance(node, ast.Subscript):
        try:
            return ast.Constant(value=1 if ast.unparse(node) == var else 0)
        except Exception:
            return ast.Constant(value=0)

    raise CalcError(f"diff(): can't differentiate {ast.unparse(node)}.")


class _DecToLit(ast.NodeTransformer):
    """dec("3.5") (how numbers are spelled in evaluable source) -> an exact numeric literal."""
    def visit_Call(self, node):
        self.generic_visit(node)
        if (isinstance(node.func, ast.Name) and node.func.id == 'dec' and len(node.args) == 1
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            try:
                d = dec(node.args[0].value)
                if d.is_finite():
                    return _lit(d)
            except Exception:
                pass
        return node


class _NegToUnary(ast.NodeTransformer):
    """Write negative numbers as unary minus so the printed text keeps its precedence: (-4)**2, not -4**2."""
    def visit_Constant(self, node):
        d = _cv(node)
        if d is not None and d < 0:
            return ast.UnaryOp(ast.USub(), _lit(-d))
        return node


def _lambda_ast(expr: str):
    """Parse a lambda body with the calculator's own tokenizer, so 3x, x^2 and 2sin(x) work as they do in f(2)."""
    tokens = get_clean_tokens(expr)
    if not tokens:
        raise CalcError("diff(): the expression is empty.")
    src = _group_tokens(tokens, 0, len(tokens), {})
    return _DecToLit().visit(ast.parse(src, mode='eval').body)


def _symbolic_diff(expr_str: str, var: str, order: int = 1) -> str:
    try:
        node = _lambda_ast(expr_str)
        for _ in range(order):
            node = _simp(_diff_node(node, var))
        if order == 0:
            node = _simp(node)
        return ast.unparse(_NegToUnary().visit(node))
    except CalcError:
        raise
    except Exception as err:
        raise CalcError(f"Symbolic diff error: {err}")


def _diff_lambda(f, order=None):
    if not isinstance(f, Lambda):
        raise CalcError("diff() expects a Lambda (quoted expression). "
                          "Example: diff(\"sin(x)\")")
    if not f.params:
        return Lambda("0", [])
    if order is None:
        n = 1
    elif isinstance(order, dec) and order.is_finite() and order == order.to_integral_value() and order >= 0:
        n = int(order)
    else:
        raise CalcError("diff(): the order must be a whole number, 0 or more.")
    var    = f.params[0]
    d_expr = _symbolic_diff(f.expr, var, n)
    return Lambda(d_expr, f.params)


# STRING


class _Str(str):
    """A string that supports + (join) and * (repeat)."""
    def _as_dec(self):
        return dec(str(self))

    def __add__(self, o):
        if isinstance(o, str):
            return _Str(str.__add__(self, o))
        if isinstance(o, (dec, mpmath.mpc, mpmath.mpf)):
            return self._as_dec() + o
        return NotImplemented
    def __radd__(self, o):
        if isinstance(o, str):
            return _Str(o + str(self))
        if isinstance(o, (dec, mpmath.mpc, mpmath.mpf)):
            return o + self._as_dec()
        return NotImplemented
    def __sub__(self, o):
        if isinstance(o, (dec, mpmath.mpc, mpmath.mpf)):
            return self._as_dec() - o
        return NotImplemented
    def __rsub__(self, o):
        if isinstance(o, (dec, mpmath.mpc, mpmath.mpf)):
            return o - self._as_dec()
        return NotImplemented
    def __mul__(self, o):
        if isinstance(o, (dec, mpmath.mpc, mpmath.mpf)):
            return self._as_dec() * o
        if isinstance(o, int):
            return _Str(str.__mul__(self, o))
        return NotImplemented
    def __rmul__(self, o):
        if isinstance(o, (dec, mpmath.mpc, mpmath.mpf)):
            return o * self._as_dec()
        if isinstance(o, int):
            return _Str(str.__mul__(self, o))
        return NotImplemented
    def __truediv__(self, o):
        if isinstance(o, (dec, mpmath.mpc, mpmath.mpf)):
            return self._as_dec() / o
        return NotImplemented
    def __rtruediv__(self, o):
        if isinstance(o, (dec, mpmath.mpc, mpmath.mpf)):
            return o / self._as_dec()
        return NotImplemented
    def __pow__(self, o):
        if isinstance(o, (dec, mpmath.mpc, mpmath.mpf)):
            return self._as_dec() ** o
        return NotImplemented
    def __rpow__(self, o):
        if isinstance(o, (dec, mpmath.mpc, mpmath.mpf)):
            return o ** self._as_dec()
        return NotImplemented
    def __neg__(self):
        return -self._as_dec()
    def __pos__(self):
        return self._as_dec()
    def __abs__(self):
        return abs(self._as_dec())


def _catkey(*args):
    parts = []
    for a in args:
        if isinstance(a, str):
            parts.append(a)
        elif isinstance(a, (dec, _DisplayDec)):
            parts.append(str(int(a)) if a == a.to_integral_value() else str(a))
        else:
            parts.append(str(a))
    return _Str(''.join(parts))


_sfstr_to_mangled = {}
_mangled_to_sfstr = {}


def _register_sfstr(inner: str) -> str:
    if inner not in _sfstr_to_mangled:
        n = len(_sfstr_to_mangled)
        m = f"XSFSTRx{n}x"
        _sfstr_to_mangled[inner] = m
        _mangled_to_sfstr[m]     = inner
    return _sfstr_to_mangled[inner]


def _is_sfstr(s: str) -> bool:
    return s in _mangled_to_sfstr


def _unmangle(text: str) -> str:
    """Show the user's own spelling (_name_, [text]) instead of the internal XLONGx0x / XSFSTRx0x placeholders."""
    text = re.sub(r'XLONGx\d+x', lambda m: f"_{_longvar_inner(m.group(0))}_" if _is_longvar(m.group(0)) else m.group(0), text)
    return re.sub(r'XSFSTRx\d+x', lambda m: f"[{_sfstr_inner(m.group(0))}]" if _is_sfstr(m.group(0)) else m.group(0), text)


def _sfstr_inner(s: str) -> str:
    return _mangled_to_sfstr.get(s, s)


def _strip_sfstrings(tokens: list):
    fmt_parts = []
    value_tokens = []
    for i, t in enumerate(tokens):
        if t.type == _TOK_SFSTRING:
            is_subscript_key = (i >= 2 and tokens[i-1].string == '[' and
                                 (tokens[i-2].type == tokenize.NAME or
                                  tokens[i-2].string in (')', ']', '}')))
            if is_subscript_key:
                value_tokens.append(t)
                if not fmt_parts or fmt_parts[-1][0] != 'value':
                    fmt_parts.append(('value',))
            else:
                fmt_parts.append(('sfstr', _sfstr_inner(t.string)))
        else:
            value_tokens.append(t)
            if not fmt_parts or fmt_parts[-1][0] != 'value':
                fmt_parts.append(('value',))
    return fmt_parts, value_tokens


_last_fmt_parts: list = [('value',)]


def _extract_format_sfstrings(tokens: list):
    fmt_parts = []; cleaned = []; bracket_depth = 0; paren_depth = 0; brace_depth = 0
    for t in tokens:
        if t.string == '[':
            bracket_depth += 1; cleaned.append(t)
        elif t.string == ']':
            if bracket_depth > 0: bracket_depth -= 1
            cleaned.append(t)
        elif t.string == '(':
            paren_depth += 1; cleaned.append(t)
        elif t.string == ')':
            if paren_depth > 0: paren_depth -= 1
            cleaned.append(t)
        elif t.string == '{':
            brace_depth += 1; cleaned.append(t)
        elif t.string == '}':
            if brace_depth > 0: brace_depth -= 1
            cleaned.append(t)
        elif t.type == _TOK_SFSTRING:
            if bracket_depth > 0 or paren_depth > 0 or brace_depth > 0 or (cleaned and cleaned[-1].string == '!'):
                cleaned.append(t)
            else:
                fmt_parts.append(('sfstr', _sfstr_inner(t.string)))
        else:
            cleaned.append(t)
            if bracket_depth == 0 and paren_depth == 0 and brace_depth == 0 and (not fmt_parts or fmt_parts[-1][0] != 'value'):
                fmt_parts.append(('value',))
    return cleaned, fmt_parts


def _apply_sfstr_format(fmt_parts: list, result_str: str) -> str:
    if not any(p[0] == 'sfstr' for p in fmt_parts):
        return result_str
    if _is_error_text(result_str):
        return result_str
    return ''.join(p[1] if p[0] == 'sfstr' else result_str for p in fmt_parts)


class _SFStrResult:
    """Result of an input that is only [text]: it just prints the text."""
    pass


_SFSTR_RESULT = _SFStrResult()


# SET


class _FmtVal:
    """A set member with attached [text] shown next to it."""
    __slots__ = ('value', 'fmt_parts')
    def __init__(self, value, fmt_parts):
        self.value = value
        self.fmt_parts = fmt_parts


def _make_fmtval(value, fmt_parts):
    return _FmtVal(value, fmt_parts)


class SetObj:
    """A set: finite `values` or continuous `clauses`, plus index `overrides` and `modificators`."""
    __slots__ = ('kind', 'values', 'clauses', 'rows', 'cols', 'overrides', 'modificators')

    def __init__(self, kind, values=None, clauses=None, rows=None, cols=None, overrides=None, modificators=None):
        self.kind         = kind
        self.values       = values
        self.clauses      = clauses
        self.rows         = rows
        self.cols         = cols
        self.overrides    = overrides if overrides is not None else {}
        self.modificators = modificators if modificators is not None else []

    def copy(self, **changes):
        """A copy of this set with the given fields replaced."""
        fields = dict(kind=self.kind,
                      values=None if self.values is None else list(self.values),
                      clauses=None if self.clauses is None else list(self.clauses),
                      rows=self.rows, cols=self.cols,
                      overrides=dict(self.overrides), modificators=list(self.modificators))
        fields.update(changes)
        return SetObj(**fields)

    def _bounds(self):
        if self.kind == 'ineq':
            los = [c[0] for c in self.clauses]
            his = [c[2] for c in self.clauses]
            return min(los), max(his)
        if self.kind in ('list', 'range', 'zeros'):
            return dec(0), dec(len(self.values) - 1)
        return dec('-Infinity'), dec('Infinity')

    def _bounds_incl(self):
        L, U = self._bounds()
        L_incl = any(c[0] == L and c[1] for c in self.clauses)
        U_incl = any(c[2] == U and c[3] for c in self.clauses)
        return L, L_incl, U, U_incl

    def _matching_clause(self, v):
        for cl in self.clauses:
            lo, lo_i, hi, hi_i, override = cl
            ok_lo = v >= lo if lo_i else v > lo
            ok_hi = v <= hi if hi_i else v < hi
            if ok_lo and ok_hi:
                return cl
        return None

    def _intersect(self, other):
        L, U = self._bounds()
        clauses = other.clauses if other.kind == 'ineq' else [(dec(0), True, dec(len(other.values) - 1), True, None)]
        result = []
        for lo2, lo2_i, hi2, hi2_i, label2 in clauses:
            lo, lo_i = (L, True) if L > lo2 else (lo2, lo2_i)
            hi, hi_i = (U, True) if U < hi2 else (hi2, hi2_i)
            if lo < hi or (lo == hi and lo_i and hi_i):
                result.append((lo, lo_i, hi, hi_i, None))
        if not result:
            result = [(dec(0), True, dec(0), False, None)]
        return SetObj('ineq', clauses=result)

    def _canon(self):
        return (frozenset(str(SetObj._unwrap(v)) for v in (self.values or [])),
                frozenset((k if isinstance(k, str) else str(k), str(v)) for k, v in self.overrides.items()),
                frozenset((op, str(o), str(n)) for op, o, n in self.modificators),
                frozenset((str(c[0]), c[1], str(c[2]), c[3]) for c in (self.clauses or [])))

    def __eq__(self, o):
        if not isinstance(o, SetObj): return NotImplemented
        return self._canon() == o._canon()
    def __ne__(self, o):
        r = self.__eq__(o)
        return r if r is NotImplemented else not r
    __hash__ = None

    def _subset_pair(self, o):
        if not isinstance(o, SetObj): return None
        if self.kind == 'ineq' or o.kind == 'ineq' or self.overrides or o.overrides or self.modificators or o.modificators:
            raise CalcError("Set ordering (<, >, <=, >=) is only supported for plain finite sets.")
        return (frozenset(str(SetObj._unwrap(v)) for v in self.values),
                frozenset(str(SetObj._unwrap(v)) for v in o.values))
    def __lt__(self, o):
        p = self._subset_pair(o); return NotImplemented if p is None else p[0] < p[1]
    def __le__(self, o):
        p = self._subset_pair(o); return NotImplemented if p is None else p[0] <= p[1]
    def __gt__(self, o):
        p = self._subset_pair(o); return NotImplemented if p is None else p[0] > p[1]
    def __ge__(self, o):
        p = self._subset_pair(o); return NotImplemented if p is None else p[0] >= p[1]

    @staticmethod
    def _to_scalar(v):
        if isinstance(v, mpmath.mpc):
            if abs(v.imag) > dec('1e-30'):
                raise CalcError("Set arithmetic requires a real number.")
            return dec(mpmath.nstr(v.real, mpmath.mp.dps))
        if isinstance(v, (dec, _DisplayDec)):
            return dec(v)
        return None

    @staticmethod
    def _unwrap(item):
        return item.value if isinstance(item, _FmtVal) else item

    @staticmethod
    def _apply_modop(op, base, operand):
        if op == '+':  return base + operand
        if op == '-':  return base - operand
        if op == '*':  return base * operand
        if op == '/':  return base / operand
        if op == '//': return _op_floordiv(base, operand)
        if op == '**': return ctx.power(base, operand)
        if op == '~':  return _round_int(base)
        raise CalcError(f"'{op}' is not supported as a set index modificator.")

    def _finite_arith(self, scalar, op):
        raw = [SetObj._unwrap(x) for x in self.values]
        if op == '+':
            if scalar in raw: return self.copy()
            return self.copy(values=list(self.values) + [scalar])
        if op == '-':
            return self.copy(values=[x for x, r in zip(self.values, raw) if r != scalar])
        fn = {'*': lambda a: a * scalar, '/': lambda a: a / scalar,
              '//': lambda a: _op_floordiv(a, scalar),
              '**': lambda a: ctx.power(a, scalar) if isinstance(a, dec) else a ** scalar}[op]
        return self.copy(values=[fn(r) for r in raw])

    def _ineq_arith(self, scalar, op):
        if op in ('//', '**'):
            raise CalcError(f"'{op}' is not supported on a continuous set range.")

        def apply(v):
            if v.is_infinite(): return v
            return {'+': v + scalar, '-': v - scalar, '*': v * scalar, '/': v / scalar}[op]
        flip = op in ('*', '/') and scalar < 0
        new_clauses = []
        for lo, lo_i, hi, hi_i, fmt in self.clauses:
            a, b = apply(lo), apply(hi)
            if flip:
                a, b, lo_i, hi_i = b, a, hi_i, lo_i
            new_clauses.append((a, lo_i, b, hi_i, fmt))
        return SetObj('ineq', clauses=new_clauses)

    def _arith(self, other, op, flipped=False):
        if isinstance(other, SetObj):
            if op in ('+', '|'):
                return self._union(other)
            if op == '-' and self.kind != 'ineq' and other.kind != 'ineq':
                raw_other = {SetObj._unwrap(x) for x in other.values}
                return self.copy(values=[x for x in self.values if SetObj._unwrap(x) not in raw_other])
            return NotImplemented
        scalar = SetObj._to_scalar(other)
        if scalar is None:
            return NotImplemented
        if flipped and op in ('-', '/', '//', '**'):
            raise CalcError(f"'{op}' is not supported with a set on the right-hand side.")
        if self.kind == 'ineq':
            return self._ineq_arith(scalar, op)
        return self._finite_arith(scalar, op)

    def _union(self, other):
        if self.kind == 'ineq' or other.kind == 'ineq':
            def to_clauses(s):
                if s.kind == 'ineq':
                    return list(s.clauses)
                out = []
                for x in s.values:
                    v = SetObj._unwrap(x)
                    v = v if isinstance(v, dec) else SetObj._to_scalar(v)
                    if v is not None:
                        out.append((v, True, v, True, None))
                return out
            return SetObj('ineq', clauses=to_clauses(self) + to_clauses(other))
        raw = [SetObj._unwrap(x) for x in self.values]
        merged = list(self.values)
        for x in other.values:
            r = SetObj._unwrap(x)
            if r not in raw:
                merged.append(x); raw.append(r)
        return self.copy(values=merged, overrides={**self.overrides, **other.overrides},
                         modificators=list(self.modificators) + list(other.modificators))

    def __add__(self, o):       return self._arith(o, '+')
    def __radd__(self, o):      return self._arith(o, '+', True)
    def __sub__(self, o):       return self._arith(o, '-')
    def __rsub__(self, o):      return self._arith(o, '-', True)
    def __mul__(self, o):       return self._arith(o, '*')
    def __rmul__(self, o):      return self._arith(o, '*', True)
    def __truediv__(self, o):   return self._arith(o, '/')
    def __rtruediv__(self, o):  return self._arith(o, '/', True)
    def __floordiv__(self, o):  return self._arith(o, '//')
    def __rfloordiv__(self, o): return self._arith(o, '//', True)
    def __pow__(self, o):       return self._arith(o, '**')
    def __rpow__(self, o):      return self._arith(o, '**', True)
    def __or__(self, o):
        return self._union(o) if isinstance(o, SetObj) else NotImplemented
    def __ror__(self, o):
        return self._union(o) if isinstance(o, SetObj) else NotImplemented

    def __getitem__(self, key):
        if self.kind == 'zeros2d':
            if not isinstance(key, tuple) or len(key) != 2:
                raise CalcError("2D Set requires two indices: s[r,c]")
            r, c = key
            r = r if isinstance(r, dec) else dec(str(r))
            c = c if isinstance(c, dec) else dec(str(c))
            r = int(r.to_integral_value(rounding=decimal.ROUND_HALF_UP)) % self.rows
            c = int(c.to_integral_value(rounding=decimal.ROUND_HALF_UP)) % self.cols
            return dec(0)

        if isinstance(key, SetObj):
            return self._intersect(key)

        if isinstance(key, tuple):
            return _make_set_list(*[self[k] for k in key])

        if isinstance(key, str):
            if key in self.overrides:
                return self.overrides[key]
            raise CalcError(f"Set has no entry for key [{key}].")

        if isinstance(key, mpmath.mpc):
            if abs(key.imag) > 1e-30:
                raise CalcError("Set indices must be real.")
            key = dec(mpmath.nstr(key.real, mpmath.mp.dps))

        v = key if isinstance(key, dec) else dec(str(key))

        if v in self.overrides:
            return self.overrides[v]

        if self.modificators:
            base = v
            for op, operand, modulus in self.modificators:
                idx = base if (modulus is None or modulus == 0) else (base % modulus)
                base = SetObj._apply_modop(op, idx, operand)
            return base

        if self.kind == 'ineq':
            cl = self._matching_clause(v)
            if cl is not None:
                result, fmt_parts = v, cl[4]
            else:
                L, L_incl, U, U_incl = self._bounds_incl()
                if U.is_infinite() and L.is_infinite():
                    result = v
                elif U.is_infinite():
                    result = U
                elif L.is_infinite():
                    result = L
                else:
                    width = U - L
                    offset = (v - L) % width
                    if offset < 0:
                        offset += width
                    if offset == 0:
                        result = U if U_incl else U.next_minus(context=decimal.Context(prec=DISPLAY_PREC))
                    else:
                        result = L + offset
                fmt_parts = next((c[4] for c in self.clauses if c[4] is not None), None)
            if fmt_parts is not None:
                return _apply_sfstr_format(fmt_parts, _fmt_element(result))
            return result

        n = len(self.values)
        if n == 0:
            raise CalcError("Set is empty.")
        idx = int(v.to_integral_value(rounding=decimal.ROUND_HALF_UP)) % n
        item = self.values[idx]
        if isinstance(item, _FmtVal):
            return _apply_sfstr_format(item.fmt_parts, _fmt_element(item.value))
        return item

    def __repr__(self):
        if self.kind == 'ineq':
            parts = []
            for lo, lo_i, hi, hi_i, fmt_parts in self.clauses:
                seg = ''
                if not (lo.is_infinite() and lo < 0):
                    seg += ('>=' if lo_i else '>') + str(_display(lo))
                if not (hi.is_infinite() and hi > 0):
                    seg += ('<=' if hi_i else '<') + str(_display(hi))
                if fmt_parts is not None:
                    texts = [p[1] for p in fmt_parts if p[0] == 'sfstr']
                    if texts:
                        seg += '[' + ''.join(texts) + ']'
                parts.append(seg)
            return '{' + ','.join(parts) + '}'
        if self.kind == 'zeros2d':
            return f'zeros({self.rows},{self.cols})'

        def fmt_val(v):
            if isinstance(v, _FmtVal):
                texts = [p[1] for p in v.fmt_parts if p[0] == 'sfstr']
                return _fmt_element(v.value) + '[' + ''.join(texts) + ']'
            return _fmt_element(v)

        def fmt_ov(k, v):
            key_txt = f'[{k}]' if isinstance(k, str) else str(int(k) if k == k.to_integral_value() else k)
            val_txt = str(v) if isinstance(v, SetObj) else fmt_val(v)
            return f'[{key_txt}]={val_txt}'
        parts = [fmt_val(v) for v in self.values]
        parts += [fmt_ov(k, v) for k, v in self.overrides.items()]
        for op, operand, n in self.modificators:
            key = '~' if op == '~' else f'{op}{operand}'
            parts.append(f"[{key}]={'>0' if op == '~' else ('>=0' if n == 0 else '>' + str(n))}")
        return '{' + ','.join(parts) + '}'

    def __str__(self):
        return self.__repr__()


def _split_ineq_clause(tokens: list):
    op1 = tokens[0].string
    j = 1
    while j < len(tokens) and tokens[j].string not in _CMP_OPS:
        j += 1
    val1 = tokens[1:j]
    if j < len(tokens):
        return op1, val1, tokens[j].string, tokens[j+1:]
    return op1, val1, None, None


def _make_clause(op1, v1, op2, v2, fmt_parts):
    v1 = v1 if isinstance(v1, dec) else dec(str(v1))
    lo, hi = dec('-Infinity'), dec('Infinity')
    lo_i, hi_i = True, True
    if op1 in ('>=', '>'):
        lo, lo_i = v1, (op1 == '>=')
    else:
        hi, hi_i = v1, (op1 == '<=')
    if op2:
        v2 = v2 if isinstance(v2, dec) else dec(str(v2))
        if op2 in ('>=', '>'):
            lo, lo_i = v2, (op2 == '>=')
        else:
            hi, hi_i = v2, (op2 == '<=')
    return (lo, lo_i, hi, hi_i, fmt_parts)


def _make_set_ineq(*clauses):
    parsed = [_make_clause(*c) for c in clauses]
    for lo, lo_i, hi, hi_i, override in parsed:
        if lo > hi or (lo == hi and not (lo_i and hi_i)):
            raise CalcError("Set clause has no valid range (e.g. '>10<0' \u2014 did you mean a comma for union, like '>10,<0'?)")
    return SetObj('ineq', clauses=parsed)


def _make_set_list(*vals):
    conv = []
    for v in vals:
        if isinstance(v, mpmath.mpf):
            v = dec(mpmath.nstr(v, mpmath.mp.dps))
        conv.append(v)
    return SetObj('list', values=conv)


def _zeros(*args):
    if len(args) == 1:
        n = int(args[0])
        return SetObj('zeros', values=[dec(0)] * n)
    if len(args) == 2:
        rows, cols = int(args[0]), int(args[1])
        return SetObj('zeros2d', rows=rows, cols=cols)
    raise CalcError("zeros() takes 1 or 2 arguments: zeros(n) or zeros(rows, cols)")


def _range_set(*args):
    """range(n) / range(a, b): the continuous set {>=a<b} (use ~range(..) for its integers)."""
    if len(args) == 1:
        lo, hi = dec(0), args[0]
    elif len(args) == 2:
        lo, hi = args
    else:
        raise CalcError("range() takes 1 or 2 arguments: range(n) or range(start, stop)")
    return _make_set_ineq(('>=', lo, '<', hi, None))


def _interval(*args):
    if len(args) == 1:
        lo, hi = dec(0), args[0]
    elif len(args) == 2:
        lo, hi = args[0], args[1]
    else:
        raise CalcError("interval() takes 1 or 2 arguments: interval(end) or interval(start, end)")
    return _make_set_ineq(('>', lo, '<', hi, None))


def _set_anchor_lo(base, offset):
    if not isinstance(base, SetObj):
        raise CalcError("inf-anchor indexing can only be used on a Set.")
    L, _ = base._bounds()
    off = offset if isinstance(offset, dec) else dec(str(offset))
    return L + off


def _set_anchor_hi(base, offset):
    if not isinstance(base, SetObj):
        raise CalcError("inf-anchor indexing can only be used on a Set.")
    _, U = base._bounds()
    off = offset if isinstance(offset, dec) else dec(str(offset))
    return U + off


def _round_obj(v):
    """Prefix '~': round a number, or turn a set into its rounded/integer set."""
    if isinstance(v, ImgNum):
        return _img_norm({m: _round_int(c) for m, c in v.p.items()})
    if isinstance(v, mpmath.mpc):
        return mpmath.mpc(mpmath.nint(v.real), mpmath.nint(v.imag))
    if isinstance(v, dec):
        return v if (v.is_infinite() or v.is_nan()) else _round_int(v)
    if isinstance(v, SetObj):
        if v.kind == 'zeros2d':
            return v
        if v.kind == 'ineq':
            ints = []
            for lo, lo_i, hi, hi_i, _ in v.clauses:
                if lo.is_infinite() or hi.is_infinite():
                    return SetObj('list', values=[], modificators=[('~', None, dec(0))])
                k = lo.to_integral_value(rounding=decimal.ROUND_CEILING)
                if k == lo and not lo_i: k += 1
                if (hi - k) > 1000000:
                    raise CalcError("~: range is too large to list its integers.")
                while k < hi or (k == hi and hi_i):
                    if k not in ints: ints.append(k)
                    k += 1
            return SetObj('list', values=ints)
        seen, out = [], []
        for x in v.values:
            r = _round_obj(SetObj._unwrap(x))
            if r not in seen:
                seen.append(r); out.append(r)
        return v.copy(values=out)
    raise CalcError("~ can only round numbers and sets.")


_ANCHOR_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\[\s*(-)?\s*\binf\b\s*([+\-]\s*[^\[\]]*)?\]')


def _preprocess_set_anchors(s: str) -> str:
    def repl(m):
        base, neg, off = m.group(1), m.group(2), m.group(3)
        offset = off.strip() if off else '+0'
        fn = 'setanchorlo' if neg else 'setanchorhi'
        return f'{fn}({base},{offset})'
    return _ANCHOR_RE.sub(repl, s)


_CMP_OPS = ('>=', '<=', '>', '<')


def _split_tokens_top_level(tokens: list, sep: str) -> list:
    parts, current, depth = [], [], 0
    for t in tokens:
        if t.string in ('(', '[', '{'):
            depth += 1; current.append(t)
        elif t.string in (')', ']', '}'):
            depth -= 1; current.append(t)
        elif t.string == sep and depth == 0:
            parts.append(current); current = []
        else:
            current.append(t)
    parts.append(current)
    return parts


def _split_index_def_seg(value_tokens):
    """If a set-literal segment is '[' <key> ']' '=' <rhs>, return (key_tokens, rhs_tokens)."""
    if not value_tokens or value_tokens[0].string != '[':
        return None
    depth = 1; j = 1
    while j < len(value_tokens) and depth > 0:
        if value_tokens[j].string == '[': depth += 1
        elif value_tokens[j].string == ']': depth -= 1
        j += 1
    if j >= len(value_tokens) or value_tokens[j].string != '=':
        return None
    key_tokens, rhs_tokens = value_tokens[1:j-1], value_tokens[j+1:]
    if not rhs_tokens:
        return None
    return key_tokens, rhs_tokens


def _index_def_key_src(key_tokens, v_dict):
    if len(key_tokens) == 1 and key_tokens[0].type == _TOK_SFSTRING:
        return repr(_sfstr_inner(key_tokens[0].string))
    return _group_tokens(key_tokens, 0, len(key_tokens), v_dict)


def _apply_set_overrides(s, pairs):
    if not isinstance(s, SetObj):
        s = _make_set_list(s)
    overrides = dict(s.overrides)
    for k, v in pairs:
        overrides[k if isinstance(k, str) else (k if isinstance(k, dec) else dec(str(k)))] = v
    return s.copy(overrides=overrides)


_MODOP_CHARS = ('**', '//', '+', '-', '*', '/', '|')
_MOD_CMP_OPS = ('>=', '>', '<=', '<')


def _split_modificator_seg(value_tokens):
    if not value_tokens or value_tokens[0].string != '[':
        return None
    depth = 1; j = 1
    while j < len(value_tokens) and depth > 0:
        if value_tokens[j].string == '[': depth += 1
        elif value_tokens[j].string == ']': depth -= 1
        j += 1
    if j >= len(value_tokens) or value_tokens[j].string != '=':
        return None
    key_tokens, rhs_tokens = value_tokens[1:j-1], value_tokens[j+1:]
    if not key_tokens or key_tokens[0].string not in _MODOP_CHARS + ('~',):
        return None
    if len(key_tokens) < 2 and key_tokens[0].string != '~':
        return None
    if not rhs_tokens or rhs_tokens[0].string not in _MOD_CMP_OPS:
        return None
    n_tokens = rhs_tokens[1:]
    if not n_tokens:
        return None
    return key_tokens[0].string, key_tokens[1:], n_tokens


def _apply_set_modificators(s, mods):
    if not isinstance(s, SetObj):
        s = _make_set_list(s)
    modificators = list(s.modificators) + mods
    return s.copy(modificators=modificators)


def _build_set_source(tokens: list, v_dict: dict) -> str:
    if not tokens:
        return '_make_set_list()'
    all_segs = [seg for seg in _split_tokens_top_level(tokens, ',') if seg]
    if not all_segs:
        return '_make_set_list()'

    index_defs = []
    modificators = []
    segs = []
    for seg in all_segs:
        moddef = _split_modificator_seg(seg)
        idxdef = None if moddef is not None else _split_index_def_seg(seg)
        if moddef is not None:
            op, operand_tokens, n_tokens = moddef
            operand_src = _group_tokens(operand_tokens, 0, len(operand_tokens), v_dict) if operand_tokens else 'None'
            n_src = _group_tokens(n_tokens, 0, len(n_tokens), v_dict)
            modificators.append(f"('{op}',({operand_src}),({n_src}))")
        elif idxdef is not None:
            key_tokens, rhs_tokens = idxdef
            key_src = _index_def_key_src(key_tokens, v_dict)
            val_src = _group_tokens(rhs_tokens, 0, len(rhs_tokens), v_dict)
            index_defs.append(f'({key_src},({val_src}))')
        else:
            segs.append(seg)

    if not segs:
        base_src = '_make_set_list()'
    else:
        parsed_segs = []
        for seg in segs:
            fmt_parts, value_tokens = _strip_sfstrings(seg)
            has_fmt = any(p[0] == 'sfstr' for p in fmt_parts)
            is_clause = bool(value_tokens) and value_tokens[0].string in _CMP_OPS
            parsed_segs.append((is_clause, has_fmt, fmt_parts, value_tokens))

        all_ineq = bool(parsed_segs) and all(p[0] for p in parsed_segs)

        if all_ineq:
            clause_srcs = []
            for is_clause, has_fmt, fmt_parts, value_tokens in parsed_segs:
                op1, val1, op2, val2 = _split_ineq_clause(value_tokens)
                v1 = _group_tokens(val1, 0, len(val1), v_dict) if val1 else '0'
                fsrc = repr(fmt_parts) if has_fmt else 'None'
                if op2:
                    v2 = _group_tokens(val2, 0, len(val2), v_dict) if val2 else '0'
                    clause_srcs.append(f"('{op1}',({v1}),'{op2}',({v2}),{fsrc})")
                else:
                    clause_srcs.append(f"('{op1}',({v1}),None,None,{fsrc})")
            base_src = f"_make_set_ineq({','.join(clause_srcs)})"
        else:
            seg_srcs = []
            for is_clause, has_fmt, fmt_parts, value_tokens in parsed_segs:
                if is_clause:
                    op1, val1, op2, val2 = _split_ineq_clause(value_tokens)
                    v1 = _group_tokens(val1, 0, len(val1), v_dict) if val1 else '0'
                    op2_src = f"'{op2}'" if op2 else 'None'
                    v2_src = f"({_group_tokens(val2, 0, len(val2), v_dict) if val2 else '0'})" if op2 else 'None'
                    fsrc = repr(fmt_parts) if has_fmt else 'None'
                    seg_srcs.append(f"_make_set_ineq(('{op1}',({v1}),{op2_src},{v2_src},{fsrc}))")
                elif has_fmt and not value_tokens:
                    continue
                elif has_fmt:
                    value_src = _group_tokens(value_tokens, 0, len(value_tokens), v_dict)
                    seg_srcs.append(f"_make_fmtval({value_src},{repr(fmt_parts)})")
                else:
                    seg_srcs.append(_group_tokens(value_tokens, 0, len(value_tokens), v_dict))
            base_src = f"_make_set_list({','.join(seg_srcs)})"

    if index_defs:
        base_src = f"_apply_set_overrides({base_src},[{','.join(index_defs)}])"
    if modificators:
        base_src = f"_apply_set_modificators({base_src},[{','.join(modificators)}])"
    return base_src


# FUNCTION


dco = {
    name: getattr(ctx, name)
    for name in dir(ctx)
    if not name.startswith('_') and callable(getattr(ctx, name))
}


_TRIG_NOISE = {'sin', 'cos', 'tan', 'cot', 'sec', 'csc', 'sinc'}
_PAIRED_INTERVALS = {'nsum', 'nprod'}
_POINT_LIST = {'quad', 'quadgl', 'quadts'}


def _make_wrapper(func, name=''):
    scrub = name in _TRIG_NOISE

    def wrapper(*args):
        if any(isinstance(a, ImgNum) for a in args):
            return _img_via_unit(wrapper, args, name)
        mp_args = [_to_mp_arg(a, name) for a in args]
        rest = mp_args[1:]
        if mp_args and callable(mp_args[0]) and rest and all(isinstance(x, (mpmath.mpf, mpmath.mpc)) for x in rest):
            if name in _PAIRED_INTERVALS and len(rest) % 2 == 0:
                mp_args = [mp_args[0]] + [rest[i:i + 2] for i in range(0, len(rest), 2)]
            elif name in _POINT_LIST:
                mp_args = [mp_args[0], rest]
        try:
            result = func(*mp_args)
        except (TypeError, ValueError) as ex:
            msg = str(ex).splitlines()[0]
            odd = next((a for a in args if isinstance(a, (SetObj, Lambda))), None)
            if odd is not None and 'cannot create' in msg:
                _to_mpf(odd, name)
            if isinstance(ex, ValueError):
                raise
            m = re.match(r'^[\w.<>]+\(\)\s+(.*)$', msg)
            raise CalcError(f"{name}() {_tidy_pyerror(m.group(1)).replace('positional argument', 'argument')}" if m and name
                            else f"{name + '(): ' if name else ''}{_tidy_pyerror(msg)}") from None
        result = _from_mp_result(result)
        if name == 'limit' and isinstance(result, dec) and result.is_finite() and abs(result) < dec(10) ** -ctx.prec:
            return dec(0)
        if scrub and isinstance(result, dec) and result.is_finite():
            nums = [abs(x) for x in mp_args if isinstance(x, (mpmath.mpf, mpmath.mpc))]
            size = max(nums) if nums else 0
            if mpmath.isfinite(size) and size >= 1 and abs(result) < dec(10) ** -(ctx.prec - 3) * dec(str(size)):
                return dec(0)
        return result
    return wrapper


for _name in dir(mpmath):
    if _name.startswith('_'):
        continue
    _obj = getattr(mpmath, _name)
    if isinstance(_obj, mpmath.ctx_mp_python.mpnumeric):
        try:
            _s = mpmath.nstr(_obj, 55, strip_zeros=False)
            if 'j' not in _s:
                dco[_name] = dec(_s)
                continue
        except Exception:
            pass
    if callable(_obj) and not inspect.isclass(_obj):
        dco[_name] = _make_wrapper(_obj, _name)


def _int(x):  return dec(int(x))


def _round(x, n=dec(0)):
    if isinstance(x, ImgNum):
        return _img_norm({m: _round(c, n) for m, c in x.p.items()})
    return x.quantize(dec(10) ** -int(n), rounding=decimal.ROUND_HALF_EVEN)


def _hydrogen_e(n):
    n = int(n)
    if n < 1: raise CalcError("hydrogen_e: n must be ≥ 1")
    return _to_dec(mpmath.mpf('-1') / (2 * n * n))


def _findroot(f, *x0):
    if not isinstance(f, Lambda):
        raise CalcError("findroot() expects a Lambda (quoted expression) as first argument. "
                          "Example: findroot(\"x**2-4\", 1)")
    if not f.params:
        raise CalcError("findroot(): expression has no free variable.")

    def mp_f(*args):
        v = {name: dec(mpmath.nstr(val, ctx.prec + 5)) for name, val in zip(f.params, args)}
        r = cal(f.expr, v, nodisplay=True)
        if not isinstance(r, dec):
            raise ValueError(str(r))
        return mpmath.mpf(str(r))

    x0_mp  = [mpmath.mpf(str(x)) for x in x0]
    x0_arg = tuple(x0_mp) if len(x0_mp) > 1 else x0_mp[0]
    result = mpmath.findroot(mp_f, x0_arg)
    return _to_dec(result)


def _integrate(f, a, b):
    if not isinstance(f, Lambda):
        raise CalcError("integrate() expects a Lambda (quoted expression) as first argument. "
                          "Example: integrate(\"sin(x)\", 0, pi)")
    if not f.params:
        raise CalcError("integrate(): expression has no free variable.")
    var = f.params[0]

    def _lim(v):
        if not isinstance(v, dec):
            return None
        if v.is_infinite():
            return mpmath.inf if v > 0 else -mpmath.inf
        return mpmath.mpf(str(v))

    a_mp, b_mp = _lim(a), _lim(b)
    if a_mp is None or b_mp is None:
        raise CalcError("integrate(): limits must be numeric.")

    def integrand(t):
        v = dec(mpmath.nstr(t, ctx.prec + 5))
        r = cal(f.expr, {var: v}, nodisplay=True, allow_inf=True)
        if isinstance(r, dec):
            return mpmath.mpf(str(r)) if r.is_finite() else _to_mpf(r)
        if isinstance(r, mpmath.mpc):
            return r
        raise CalcError(f"integrate(): {_error_text(r)}" if isinstance(r, str) else "integrate(): the expression is not a number.")

    points = [a_mp, 0, b_mp] if a_mp < 0 < b_mp else [a_mp, b_mp]
    try:
        result, err = mpmath.quad(integrand, points, error=True)
    except CalcError:
        raise
    except Exception as err:
        raise CalcError(f"integrate(): {err}")
    if not mpmath.isfinite(result) or err > mpmath.mpf(10) ** -10 * max(1, abs(result)):
        raise CalcError("integrate(): the integral does not seem to converge.")

    result_dec = dec(mpmath.nstr(result, mpmath.mp.dps)) if isinstance(result, mpmath.mpf) else result
    if isinstance(result_dec, dec) and abs(result_dec) < dec('1e-' + str(ctx.prec - 2)):
        result_dec = dec(0)
    return result_dec


def _schrodinger(V, n, xmin, xmax, Npts=dec(100)):
    if not isinstance(V, Lambda):
        raise CalcError("schrodinger() expects a Lambda (quoted expression) as first argument. "
                          "Example: schrodinger(\"x**2/2\", 0, -8, 8)")
    if not V.params:
        raise CalcError("schrodinger(): expression has no free variable.")
    var    = V.params[0]
    n      = int(n)
    Npts   = int(Npts)
    xmin_m = mpmath.mpf(str(xmin))
    xmax_m = mpmath.mpf(str(xmax))
    dx      = (xmax_m - xmin_m) / (Npts + 1)
    inv_dx2 = 1 / dx**2
    H = mpmath.matrix(Npts, Npts)
    for i in range(Npts):
        xi = xmin_m + (i + 1) * dx
        vi = cal(V.expr, {var: dec(mpmath.nstr(xi, 30))}, nodisplay=True)
        if not isinstance(vi, dec):
            raise CalcError(f"schrodinger(): {_error_text(vi)}")
        Vi = mpmath.mpf(str(vi))
        H[i, i] = inv_dx2 + Vi
        if i + 1 < Npts:
            H[i, i+1] = -inv_dx2 / 2; H[i+1, i] = -inv_dx2 / 2
    E, _ = mpmath.eigsy(H)
    vals = sorted([E[i] for i in range(Npts)], key=lambda v: float(mpmath.re(v)))
    if n >= len(vals):
        raise CalcError(f"schrodinger(): n={n} out of range (max {len(vals)-1})")
    return dec(mpmath.nstr(vals[n], mpmath.mp.dps))


def _solve_anharmonic(n, c):
    n = int(n); c = mpmath.mpf(str(c))
    N = max(60, n + 50)
    A = mpmath.matrix(N, N)
    for i in range(N):
        A[i, i] = (i + mpmath.mpf('0.5')) + c * (6*i*i + 6*i + 3) / 4
        if i + 2 < N:
            v2 = c * (2*i + 3) * mpmath.sqrt((i+1)*(i+2)) / 2
            A[i, i+2] = v2; A[i+2, i] = v2
        if i + 4 < N:
            v4 = c * mpmath.sqrt((i+1)*(i+2)*(i+3)*(i+4)) / 4
            A[i, i+4] = v4; A[i+4, i] = v4
    E, _ = mpmath.eigsy(A)
    vals  = sorted([E[i] for i in range(N)], key=lambda v: float(mpmath.re(v)))
    return dec(mpmath.nstr(vals[n], mpmath.mp.dps))


def _dec_fn(*args):
    if not args:
        raise CalcError("dec() requires at least one argument.")
    total = dec(0)
    for x in args:
        if isinstance(x, dec):
            total += x
        elif isinstance(x, mpmath.mpc):
            im = dec(mpmath.nstr(x.imag, mpmath.mp.dps))
            if abs(im) < dec('1e-30'):
                total += dec(mpmath.nstr(x.real, mpmath.mp.dps))
            else:
                raise CalcError("dec(): cannot convert a complex number with nonzero imaginary part.")
        elif isinstance(x, mpmath.mpf):
            total += dec(mpmath.nstr(x, mpmath.mp.dps))
        elif isinstance(x, Lambda):
            r = x()
            if isinstance(r, _MissingArgs):
                return r
            if isinstance(r, str):
                return r
            if isinstance(r, mpmath.mpc):
                im = dec(mpmath.nstr(r.imag, mpmath.mp.dps))
                if abs(im) < dec('1e-30'):
                    r = dec(mpmath.nstr(r.real, mpmath.mp.dps))
                else:
                    raise CalcError("dec(): cannot convert a complex number with nonzero imaginary part.")
            elif isinstance(r, mpmath.mpf):
                r = dec(mpmath.nstr(r, mpmath.mp.dps))
            elif not isinstance(r, dec):
                raise CalcError("dec(): Lambda did not evaluate to a number.")
            total += r
        elif isinstance(x, int):
            total += dec(x)
        elif isinstance(x, str):
            with decimal.localcontext() as _lc:
                _lc.traps[decimal.InvalidOperation] = True
                try:
                    total += dec(x)
                except decimal.InvalidOperation:
                    raise CalcError(f"dec(): cannot convert '{x}' to a number.")
        else:
            raise CalcError(f"dec(): cannot convert '{x}' to a number.")
    return total


def _size(*a):
    if not a:
        raise CalcError("size() needs at least one argument.")
    total = dec(0)
    for v in a:
        if isinstance(v, ImgNum):
            total += sum((c * c for c in v.p.values()), dec(0))
        elif isinstance(v, mpmath.mpc):
            total += dec(mpmath.nstr(v.real, mpmath.mp.dps)) ** 2 + dec(mpmath.nstr(v.imag, mpmath.mp.dps)) ** 2
        elif isinstance(v, (dec, _DisplayDec)):
            total += v * v
        else:
            d = dec(str(v))
            total += d * d
    return ctx.sqrt(total)


def _len_one(v):
    if isinstance(v, mpmath.mpc):
        v = dec(mpmath.nstr(v.real, mpmath.mp.dps))
    if isinstance(v, (dec, _DisplayDec)):
        if v.is_infinite() or v.is_nan():
            raise CalcError("len(): number has no finite digit count.")
        s, d, e = v.as_tuple()
        return dec(len(d))
    if isinstance(v, str):
        return dec(len(v))
    if isinstance(v, Lambda):
        return dec(len(get_clean_tokens(v.expr)))
    if isinstance(v, SetObj):
        if v.kind == 'zeros2d':
            return dec(v.rows * v.cols)
        if v.kind == 'ineq':
            L, L_incl, U, U_incl = v._bounds_incl()
            if L == U and L_incl and U_incl:
                return dec(1)
            raise CalcError("len(): set has an unbounded/continuous range, no finite item count.")
        return dec(len(v.values))
    raise CalcError(f"len(): unsupported type {type(v).__name__}")


def _len(*a):
    if not a:
        raise CalcError("len() needs at least one argument.")
    total = dec(0)
    for v in a:
        total += _len_one(v)
    return total


def _nums(args, who: str) -> list:
    """Flatten numbers and finite sets into a list of Decimals."""
    out = []
    for a in args:
        if isinstance(a, SetObj):
            if a.kind == 'ineq' or a.values is None:
                raise CalcError(f"{who}(): a continuous set has no finite members (try ~set).")
            out.extend(_nums([SetObj._unwrap(x) for x in a.values], who))
        elif isinstance(a, mpmath.mpc):
            if abs(a.imag) > dec('1e-30'): raise CalcError(f"{who}(): real numbers only.")
            out.append(dec(mpmath.nstr(a.real, mpmath.mp.dps)))
        elif isinstance(a, dec):
            out.append(dec(a))
        else:
            raise CalcError(f"{who}(): numbers or sets of numbers expected.")
    if not out: raise CalcError(f"{who}() needs at least one value.")
    return out


def _int_arg(v, who: str) -> int:
    v = _nums([v], who)[0]
    if v != v.to_integral_value(): raise CalcError(f"{who}(): whole number expected.")
    return int(v)


def _sum(*a):  return sum(_nums(a, 'sum'), dec(0))


def _prod(*a):
    r = dec(1)
    for v in _nums(a, 'prod'): r *= v
    return r


def _mean(*a):
    v = _nums(a, 'mean'); return sum(v, dec(0)) / len(v)


def _median(*a):
    v = sorted(_nums(a, 'median')); n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def _var(*a, _sample=False):
    v = _nums(a, 'var'); n = len(v)
    if _sample and n < 2: raise CalcError("svar(): needs at least 2 values.")
    m = sum(v, dec(0)) / n
    return sum(((x - m) ** 2 for x in v), dec(0)) / (n - 1 if _sample else n)


def _gcd(*a):
    import math
    return dec(math.gcd(*[_int_arg(x, 'gcd') for x in a]))


def _lcm(*a):
    import math
    r = 1
    for x in a: r = math.lcm(r, _int_arg(x, 'lcm'))
    return dec(r)


def _isprime_int(n: int) -> bool:
    if n < 2: return False
    for q in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % q == 0: return n == q
    d, r = n - 1, 0
    while d % 2 == 0: d //= 2; r += 1
    for base in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        x = pow(base, d, n)
        if x in (1, n - 1): continue
        for _ in range(r - 1):
            x = x * x % n
            if x == n - 1: break
        else: return False
    return True


def _isprime(n): return _isprime_int(_int_arg(n, 'isprime'))


def _nextprime(n):
    k = _int_arg(n, 'nextprime') + 1
    while not _isprime_int(k): k += 1
    return dec(k)


def _primes(n):
    n = _int_arg(n, 'primes')
    if n > 10_000_000: raise CalcError("primes(): limit is 10,000,000.")
    if n < 2: return SetObj('list', values=[])
    sieve = bytearray([1]) * (n + 1); sieve[0:2] = b'\x00\x00'
    for i in range(2, int(n ** 0.5) + 1):
        if sieve[i]: sieve[i*i::i] = bytearray(len(sieve[i*i::i]))
    return SetObj('list', values=[dec(i) for i in range(n + 1) if sieve[i]])


def _divisors(n):
    n = _int_arg(n, 'divisors')
    if n < 1: raise CalcError("divisors(): positive whole number expected.")
    small, large, d = [], [], 1
    while d * d <= n:
        if n % d == 0:
            small.append(d)
            if d * d != n: large.append(n // d)
        d += 1
        if d > 10_000_000: raise CalcError("divisors(): number is too large.")
    return SetObj('list', values=[dec(x) for x in small + large[::-1]])


def _npr(n, r):
    n, r = _int_arg(n, 'npr'), _int_arg(r, 'npr')
    if r < 0 or r > n: return dec(0)
    import math
    return dec(math.perm(n, r))


def _abs(x):
    if isinstance(x, ImgNum):
        return _img_via_unit(_abs, (x,), 'abs')
    if isinstance(x, mpmath.mpc):
        return _to_dec(abs(x))
    return ctx.abs(x)
def _max(*a): return max(_nums(a, 'max'))
def _min(*a): return min(_nums(a, 'min'))
def _sq(x):   return x * x


def _cube(x): return x * x * x


def _log2(x): return _to_dec(mpmath.log(mpmath.mpf(str(x)), 2))


def _clamp(x, lo, hi):
    if lo > hi: raise CalcError("clamp(): lo must not exceed hi.")
    return max(lo, min(x, hi))


def _lerp(a, b, t): return a + (b - a) * t


def _iff(cond, a, b): return a if _truthy(cond) else b


def _dist(*a):
    v = _nums(a, 'dist')
    if len(v) % 2: raise CalcError("dist(): give two points with the same number of coordinates.")
    h = len(v) // 2
    return ctx.sqrt(sum(((x - y) ** 2 for x, y in zip(v[:h], v[h:])), dec(0)))


def _digsum(n):
    return dec(sum(int(c) for c in str(abs(_int_arg(n, 'digsum')))))


def _sort(s):
    v = _nums([s], 'sort'); return SetObj('list', values=sorted(v))


def _rev(s):
    if isinstance(s, SetObj) and s.kind != 'ineq' and s.values is not None:
        return s.copy(values=list(s.values)[::-1])
    raise CalcError("rev(): a finite set expected.")


def _repeat_not_toplevel(*_):
    raise CalcError("repeat() must be a top-level call: repeat(step, ..., ticks)")


def _until_not_toplevel(*_):
    raise CalcError("until() must be a top-level call: until(step, ..., condition)")


def _successor(cur, op: str):
    """Value for an operand-less compound step such as 'x+=': a number goes up
    by 1; a finite numeric set gets its next arithmetic-progression member."""
    if op != '+':
        raise CalcError(f"'{op}=' needs a right-hand side.")
    if isinstance(cur, dec):
        return cur + 1
    if isinstance(cur, SetObj) and cur.kind != 'ineq' and cur.values is not None:
        raw = [SetObj._unwrap(v) for v in cur.values]
        if not raw:
            return cur.copy(values=[dec(0)])
        if not all(isinstance(v, dec) for v in raw):
            raise CalcError("'+=' without a value needs a set of plain numbers.")
        step = raw[-1] - raw[-2] if len(raw) > 1 else dec(1)
        return cur.copy(values=list(cur.values) + [raw[-1] + step])
    raise CalcError("'+=' without a value works on numbers and numeric sets.")


def _run_tick_arg(arg: str, work: dict, chk: bool = False):
    """Run one repeat/until step; a bare expression assigns to the first variable it mentions."""
    arg = arg.strip()
    tgt, expr = None, arg
    split = _split_assign_seg(arg)
    if split is not None:
        t, op, rhs = split[0].strip(), split[1], split[2].strip()
        if _is_assign_target(t):
            if op and not rhs:
                if t not in work:
                    raise CalcError(f"'{_longvar_inner(t) if _is_longvar(t) else t}' is not defined.")
                ev = _successor(work[t], op)
                _store_assignment(work, t, ev)
                return ev
            if not rhs:
                raise CalcError("Missing value after '='.")
            tgt, expr = t, (f'({t}){op}({rhs})' if op else rhs)
    if tgt is None:
        vs = getv(arg)
        tgt = vs[0] if vs else None
    ev = cal(expr, work, chk, nodisplay=True)
    if isinstance(ev, (dec, _CPLX, Lambda, SetObj)) and tgt is not None:
        _store_assignment(work, tgt, ev)
    return ev


_UNTIL_MAX_TICKS = 100000


def _parse_call_args(expr: str, name: str):
    s = expr.strip()
    if not (s.startswith(name + '(') and s.endswith(')')):
        return None
    return [a.strip() for a in _split_top_level(s[len(name) + 1:-1], ',')]


def _eval_repeat(expr: str, v_dict: dict, chk: bool = False):
    args = _parse_call_args(expr, 'repeat')
    if args is None or len(args) < 2 or not all(args):
        raise CalcError("repeat() syntax: repeat(step, ..., ticks)")
    steps, n_str = args[:-1], args[-1]
    if chk: return dec(1)
    n_val = cal(n_str, v_dict, chk)
    if not isinstance(n_val, dec): return n_val
    try:
        n = int(n_val)
    except Exception:
        raise CalcError("repeat() ticks must be a whole number.")
    if n <= 0: raise CalcError("repeat() ticks must be positive.")
    result = dec(0)
    try:
        for _ in range(n):
            for st in steps:
                result = _run_tick_arg(st, v_dict)
                if isinstance(result, str): return result
    except KeyboardInterrupt:
        print(f"{YELLOW}Interrupted.{RST}")
        return _BACK
    return result


def _eval_until(expr: str, v_dict: dict, chk: bool = False):
    args = _parse_call_args(expr, 'until')
    if args is None or len(args) < 2 or not all(args):
        raise CalcError("until() syntax: until(step, ..., condition)")
    steps, cond = args[:-1], args[-1]
    if chk: return dec(1)
    result = dec(0)
    try:
        for tick in range(_UNTIL_MAX_TICKS):
            for st in steps:
                result = _run_tick_arg(st, v_dict)
                if isinstance(result, str): return result
            c = cal(cond, v_dict)
            if isinstance(c, str): return c
            if _truthy(c): return result
    except KeyboardInterrupt:
        print(f"{YELLOW}Interrupted.{RST}")
        return _BACK
    raise CalcError(f"until(): condition still false after {_UNTIL_MAX_TICKS} ticks.")


def _parse_findroot(expr: str):
    s = expr.strip()
    if not (s.startswith('findroot(') and s.endswith(')')):
        return None
    body = s[9:-1]
    parts = [p.strip() for p in _split_top_level(body, ',')]
    if len(parts) < 2:
        return None
    return parts


def _eval_findroot(expr: str, v_dict: dict, chk: bool = False):
    parts = _parse_findroot(expr)
    if parts is None:
        raise CalcError("findroot() syntax: findroot(expr, x0[, x1])")

    expr_part = parts[0]
    quoted = ((expr_part.startswith('"') and expr_part.endswith('"')) or
              (expr_part.startswith("'") and expr_part.endswith("'")))
    if not quoted:
        raise CalcError("findroot() expects a Lambda (quoted expression) as first argument. "
                          "Example: findroot(\"x**2-4\", 1)")
    lam_expr = expr_part[1:-1]
    params   = _get_lambda_params(lam_expr)
    if not params:
        raise CalcError("findroot(): expression has no free variable.")
    root_var, extra = params[0], params[1:]

    if chk:
        probe_vars = {p: dec(0) for p in params}
        return cal(lam_expr, probe_vars, chk=True)

    x0_vals = []
    for p in parts[1:]:
        v = cal(p, v_dict, nodisplay=True)
        if not isinstance(v, dec):
            return v
        x0_vals.append(v)

    fixed = {}
    for name in extra:
        if name in v_dict and isinstance(v_dict[name], (dec, mpmath.mpc)):
            fixed[name] = v_dict[name]
        else:
            return _fmt_error(f"'{name}' is not defined.")

    last_err = [None]

    def mp_f(x):
        v = dict(fixed)
        v[root_var] = dec(mpmath.nstr(x, ctx.prec + 5))
        r = cal(lam_expr, v, nodisplay=True)
        if not isinstance(r, dec):
            last_err[0] = r
            raise ValueError(str(r))
        return mpmath.mpf(str(r))

    x0_mp  = [mpmath.mpf(str(x)) for x in x0_vals]
    x0_arg = tuple(x0_mp) if len(x0_mp) > 1 else x0_mp[0]

    try:
        result = mpmath.findroot(mp_f, x0_arg)
    except ValueError:
        if last_err[0] is not None:
            return last_err[0]
        try:
            result = mpmath.findroot(mp_f, x0_arg, tol=mpmath.mpf('1e-15'))
            print(f"{YELLOW}findroot: root may have multiplicity > 1; result is approximate.{RST}")
        except ValueError as err2:
            if last_err[0] is not None:
                return last_err[0]
            raise CalcError(f"findroot: {str(err2).splitlines()[0]}")

    return _display(_to_dec(result))


dco['int']    = _int
dco['round']  = _round
dco['rad']    = dco['radians']
dco['deg']    = dco['degrees']
dco['repeat'] = _repeat_not_toplevel
dco['until'] = _until_not_toplevel
dco['mpf'] = lambda x: mpmath.mpf(str(x))
dco['mpc'] = lambda r, i: mpmath.mpc(str(r), str(i))
dco['str'] = _catkey
dco['hydrogen_e'] = _hydrogen_e
dco['findroot'] = _findroot
dco['integrate'] = _integrate
dco['schrodinger'] = _schrodinger
dco['anharmonic'] = _solve_anharmonic
dco['run'] = _run_lambda
dco['zeros'] = _zeros
dco['range'] = _range_set
dco['interval'] = _interval
dco['setanchorlo'] = _set_anchor_lo
dco['setanchorhi'] = _set_anchor_hi
dco['dec'] = _dec_fn
dco['diff'] = _diff_lambda
dco['size'] = _size
dco['tif'] = lambda *a: None
dco['len'] = _len
for _n, _f in {'sum': _sum, 'prod': _prod, 'mean': _mean, 'median': _median,
               'var': _var, 'std': lambda *a: ctx.sqrt(_var(*a)),
               'svar': lambda *a: _var(*a, _sample=True), 'sstd': lambda *a: ctx.sqrt(_var(*a, _sample=True)),
               'gcd': _gcd, 'lcm': _lcm, 'isprime': _isprime, 'nextprime': _nextprime,
               'primes': _primes, 'divisors': _divisors, 'npr': _npr, 'sq': _sq, 'cube': _cube,
               'log2': _log2, 'clamp': _clamp, 'lerp': _lerp, 'mod': _op_mod, 'iff': _iff,
               'abs': _abs, 'max': _max, 'min': _min,
               'dist': _dist, 'digsum': _digsum, 'sort': _sort, 'rev': _rev}.items():
    dco[_n] = _f


_ALIASES = {
    'avg': 'mean', 'sgn': 'sign', 'fact': 'factorial', 'ncr': 'binomial', 'comb': 'binomial',
    'lgamma': 'loggamma', 'pgamma': 'polygamma', 'harm': 'harmonic', 'bern': 'bernoulli',
    'herm': 'hermite', 'lag': 'laguerre', 'leg': 'legendre', 'proots': 'polyroots',
    'pval': 'polyval', 'nroot': 'nthroot', 'lins': 'linspace', 'uvec': 'unitvector',
    'sig': 'sigmoid', 'sci': 'to_sci_string', 'eng': 'to_eng_string', 'toint': 'to_integral_value',
    'land': 'logical_and', 'lor': 'logical_or', 'lxor': 'logical_xor', 'lnot': 'logical_invert',
    'ilap': 'invertlaplace', 'uroots': 'unitroots', 'jac': 'jacobian', 'ival': 'interval',
    'rep': 'repeat', 'unt': 'until', 'froot': 'findroot',
}
for _a, _t in _ALIASES.items():
    if _t in dco and _a not in dco:
        dco[_a] = dco[_t]
_TOPLEVEL_ALIAS_RE = re.compile(r'^\s*(rep|unt|froot)\(')
_TOPLEVEL_CANON = {'rep': 'repeat', 'unt': 'until', 'froot': 'findroot'}


# CONSTANT


def _repin_constants():
    dco['e']     = _to_dec(mpmath.exp(1))
    dco['pi']    = _to_dec(mpmath.pi)
    dco['phi']   = _to_dec(mpmath.phi)
    dco['euler'] = _to_dec(mpmath.euler)
    dco['hbar']  = dec('1')
    dco['tau']   = _to_dec(2 * mpmath.pi)
    dco['sqrt2'] = _to_dec(mpmath.sqrt(2))
    dco['sqrt3'] = _to_dec(mpmath.sqrt(3))
    dco['ln3']   = _to_dec(mpmath.log(3))
    dco['log2e'] = _to_dec(1 / mpmath.log(2))
    dco['silver'] = _to_dec(1 + mpmath.sqrt(2))
    dco['omega'] = _to_dec(mpmath.lambertw(1))
    dco['light']     = dec('299792458')
    dco['planck']    = dec('6.62607015E-34')
    dco['boltzmann'] = dec('1.380649E-23')
    dco['avogadro']  = dec('6.02214076E+23')
    dco['echarge']   = dec('1.602176634E-19')
    dco['grav']      = dec('6.6743E-11')
    dco['gravity']   = dec('9.80665')


_repin_constants()
def _rebase_value(v, old_pb: int):
    """Re-express a stored number after the main unit changed: its imaginary part belonged to the unit old_pb."""
    if isinstance(v, mpmath.mpc):
        p = {}
        re_, im_ = _to_dec(v.real), _to_dec(v.imag)
        if re_ != 0: p[0] = re_
        if im_ != 0: p[old_pb] = im_
        return _img_norm(p)
    if isinstance(v, ImgNum):
        return _img_norm(dict(v.p))
    if isinstance(v, SetObj) and v.values:
        v.values = [_rebase_value(x, old_pb) if isinstance(x, _CPLX) else x for x in v.values]
    return v


def _unit_refresh(old_pb=None) -> None:
    """Make dco and IMG match the units that are on: the first is a plain complex number, the others ImgNums.
    Pass the main unit's bit from before a change so that stored numbers keep their meaning."""
    global IMG
    for key in _UNIT_KEYS:
        if isinstance(dco.get(key), _CPLX):
            del dco[key]
    _ACTIVE_UNITS[:] = [u for u in _UNIT_LIST if u not in _UNIT_OFF]
    for n, uid in enumerate(_ACTIVE_UNITS):
        dco[_UNIT_KEYS[uid]] = mpmath.mpc(0, 1) if n == 0 else ImgNum({1 << uid: dec(1)})
    IMG = bool(_ACTIVE_UNITS)
    if old_pb is not None and old_pb != _primary_bit():
        for store in (_user_vars, _const_vars):
            for k, v in list(store.items()):
                store[k] = _rebase_value(v, old_pb)


_unit_refresh()
dco['true'] = True
dco['false'] = False


_NAME_TOK_RE = r'(_[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*_|[A-Za-z])'


def _const_key(name_txt: str):
    """'x' or '_name_' -> the internal variable/constant key, or None if not a valid name."""
    key = _strip_spaces(name_txt)
    return key if (len(key) == 1 and key.isalpha()) or _is_longvar(key) else None


def _disp_name(key: str) -> str:
    return f"_{_longvar_inner(key)}_" if _is_longvar(key) else key


def _stored_value(expr: str, what: str = "Constant"):
    """Evaluate expr against the stored variables and constants; return a storable value or None (after printing why not)."""
    ev = _resolve(_strip_spaces(expr), _stored(), keep_precision=True)
    if ev is _ABORT or ev is _BACK:
        return None
    if isinstance(ev, dec): ev = dec(ev)
    if isinstance(ev, (dec, _CPLX, Lambda, SetObj)):
        return ev
    print(ev if isinstance(ev, str) else _fmt_error(f"{what} value must be a number, set or function."))
    return None


_SAVE_FILENAME = 'calculator_saves.json'


def _save_path() -> str:
    """Save file: $CALC_SAVES if set, else calculator_saves.json in the current working directory."""
    return os.environ.get('CALC_SAVES') or os.path.join(os.getcwd(), _SAVE_FILENAME)


_DEFAULT_SAVE = 'default'


def _demangle_text(t: str) -> str:
    """Make a stored expression session-independent (longvars -> _name_, string macros -> \\x01text\\x02)."""
    t = re.sub(r'XLONGx\d+x', lambda m: f"_{_longvar_inner(m.group(0))}_" if _is_longvar(m.group(0)) else m.group(0), t)
    return re.sub(r'XSFSTRx\d+x', lambda m: f"\x01{_sfstr_inner(m.group(0))}\x02" if _is_sfstr(m.group(0)) else m.group(0), t)


def _remangle_text(t: str) -> str:
    t = re.sub(r'\x01(.*?)\x02', lambda m: _register_sfstr(m.group(1)), t)
    return _preprocess_lv(t)


def _enc(v):
    if isinstance(v, bool): return {'t': 'b', 'v': v}
    if isinstance(v, ImgNum):
        return {'t': 'm', 'terms': [[[_disp_name(_UNIT_KEYS[k]) for k in _mask_bits(m)], str(c)] for m, c in v.p.items()]}
    if isinstance(v, dec):  return {'t': 'd', 'v': str(dec(v))}
    if isinstance(v, mpmath.mpc):
        return {'t': 'c', 're': mpmath.nstr(v.real, mpmath.mp.dps), 'im': mpmath.nstr(v.imag, mpmath.mp.dps)}
    if isinstance(v, str):  return {'t': 's', 'v': str(v)}
    if isinstance(v, Lambda):
        return {'t': 'l', 'expr': _demangle_text(v.expr), 'params': [_demangle_text(p) for p in v.params]}
    if isinstance(v, _FmtVal): return {'t': 'f', 'value': _enc(v.value), 'fmt': [list(p) for p in v.fmt_parts]}
    if isinstance(v, SetObj):
        return {'t': 'S', 'kind': v.kind, 'rows': v.rows, 'cols': v.cols,
                'values': None if v.values is None else [_enc(x) for x in v.values],
                'clauses': None if v.clauses is None else
                    [[_enc(c[0]), c[1], _enc(c[2]), c[3], None if c[4] is None else [list(p) for p in c[4]]] for c in v.clauses],
                'overrides': [[_enc(k), _enc(x)] for k, x in v.overrides.items()],
                'modificators': [[op, None if o is None else _enc(o), _enc(n)] for op, o, n in v.modificators]}
    raise CalcError(f"Cannot save a value of type {type(v).__name__}.")


def _dec_obj(d):
    t = d['t']
    if t == 'b': return d['v']
    if t == 'd': return dec(d['v'])
    if t == 'c': return mpmath.mpc(mpmath.mpf(d['re']), mpmath.mpf(d['im']))
    if t == 'm':
        p = {}
        for names, c in d['terms']:
            m = 0
            for nm in names:
                k = _const_key(nm)
                if k is None: raise CalcError("Corrupt save entry (bad imaginary unit).")
                m |= 1 << _unit_id(k)
            p[m] = dec(c)
        return _img_norm(p)
    if t == 's': return d['v']
    if t == 'l': return Lambda(_remangle_text(d['expr']), [_remangle_text(p) for p in d['params']])
    if t == 'f': return _FmtVal(_dec_obj(d['value']), [tuple(p) for p in d['fmt']])
    if t == 'S':
        return SetObj(d['kind'], rows=d['rows'], cols=d['cols'],
                      values=None if d['values'] is None else [_dec_obj(x) for x in d['values']],
                      clauses=None if d['clauses'] is None else
                          [(_dec_obj(c[0]), c[1], _dec_obj(c[2]), c[3], None if c[4] is None else [tuple(p) for p in c[4]])
                           for c in d['clauses']],
                      overrides={_dec_obj(k): _dec_obj(x) for k, x in d['overrides']},
                      modificators=[(op, None if o is None else _dec_obj(o), _dec_obj(n)) for op, o, n in d['modificators']])
    raise CalcError(f"Corrupt save entry (type '{t}').")


def _read_saves() -> dict:
    try:
        with open(_save_path(), encoding='utf-8') as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {'default': None, 'saves': {}}
    except (OSError, ValueError) as ex:
        raise CalcError(f"Could not read save file ({ex}).")
    data.setdefault('default', None); data.setdefault('saves', {})
    return data


def _write_saves(data: dict) -> None:
    """Persist data. The file only comes into existence on the first real save,
    is replaced atomically, and is deleted again once no saves remain."""
    path = _save_path()
    try:
        if not data['saves']:
            if os.path.exists(path): os.remove(path)
            return
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, path)
    except OSError as ex:
        raise CalcError(f"Could not write save file ({ex}).")


def _snapshot() -> dict:
    return {'vars':   {_demangle_text(k): _enc(v) for k, v in _user_vars.items()},
            'consts': {_demangle_text(k): _enc(v) for k, v in _const_vars.items()},
            'settings': {'prec': DISPLAY_PREC,
                         'units': [[_disp_name(_UNIT_KEYS[u]), u not in _UNIT_OFF] for u in _UNIT_LIST]}}


def _restore(snap: dict) -> int:
    """Apply a snapshot; if it turns out to be corrupt, the imaginary units are left as they were."""
    before = (list(_UNIT_LIST), set(_UNIT_OFF))
    try:
        return _restore_all(snap)
    except Exception:
        _UNIT_LIST[:] = before[0]; _UNIT_OFF.clear(); _UNIT_OFF.update(before[1])
        _unit_refresh()
        raise


def _restore_all(snap: dict) -> int:
    st = snap.get('settings', {})
    if 'units' in st or 'img' in st:
        raw = st.get('units', [])
        if all(isinstance(e, str) for e in raw):      # older save: an 'img' flag plus the names of extra units
            items = ([('i', True)] if st.get('img', True) else []) + [(n, True) for n in raw]
        else:
            items = [(e[0], bool(e[1])) for e in raw]
        taken = {_remangle_text(k) for k in snap['vars']} | {_remangle_text(k) for k in snap.get('consts', {})}
        _UNIT_LIST.clear(); _UNIT_OFF.clear(); _unit_refresh()
        for n, on in items:
            k = _const_key(n)
            if k is None or k in taken or k in dco or any(_UNIT_KEYS[u] == k for u in _UNIT_LIST):
                continue
            uid = _unit_id(k)
            _UNIT_LIST.append(uid)
            if not on: _UNIT_OFF.add(uid)
    _unit_refresh()
    vars_ = {_remangle_text(k): _dec_obj(v) for k, v in snap['vars'].items()}
    if 'consts' in snap:
        consts = {_remangle_text(k): _dec_obj(v) for k, v in snap['consts'].items()}
    else:
        old    = {_remangle_text(k) for k in snap.get('constants', [])}
        consts = {k: vars_.pop(k) for k in list(vars_) if k in old}
    _user_vars.clear();  _user_vars.update(vars_)
    _const_vars.clear(); _const_vars.update(consts)
    if 'prec' in st and int(st['prec']) != DISPLAY_PREC: actions(f"prec {int(st['prec'])}")
    return len(vars_) + len(consts)


def _autoload_default(announce: bool = True) -> None:
    try:
        data = _read_saves()
        if data['default'] and data['default'] in data['saves']:
            _cmd_load(data['default'], quiet=True)
            if announce: print(f"{GRAY}loaded default save '{data['default']}'{RST}")
    except CalcError as ex:
        print(_fmt_error(str(ex)))


# COMMAND


def _confirm(question: str) -> bool:
    if NO_ASK:
        return True
    try:
        return input(f"{YELLOW}{question} [y/N]{RST} ").strip().lower() in ('y', 'yes')
    except (KeyboardInterrupt, EOFError):
        print(); return False


def _show_const_added(key: str, ev, verb: str = "added") -> None:
    print(f"{GREEN}+ {_disp_name(key)}{RST} = {_fmt_result(ev)}  {GRAY}(constant {verb}){RST}")


def _unit_clash(key: str):
    """Why key cannot become an imaginary unit, or None. (Units that are off are not in dco.)"""
    name = _disp_name(key)
    if key in _const_vars:
        return f"'{name}' is a constant \u2014 remove it first: constrm {name}"
    if key in _user_vars:
        return f"'{name}' is a variable \u2014 remove it first: varrm {name}"
    if key in dco:
        return f"'{name}' is already a built-in constant or function."
    return None


def _split_names(rest: str) -> list:
    return [t for t in re.split(r'[\s,]+', rest.strip()) if t]


def _names(rest: str, usage: str) -> list:
    """The valid names in rest as internal keys, without repeats; invalid ones are reported and skipped."""
    toks = _split_names(rest)
    if not toks:
        print(_fmt_error(usage)); return []
    keys = []
    for t in toks:
        key = _const_key(t)
        if key is None:
            print(_fmt_error(f"'{t}' is not a valid name (one letter or _long_name_)."))
        elif key not in keys:
            keys.append(key)
    return keys


def _list_units() -> None:
    if not _UNIT_LIST: print(f"{GRAY}No imaginary units.{RST}"); return
    main = _ACTIVE_UNITS[0] if _ACTIVE_UNITS else None
    for uid in _UNIT_LIST:
        name = _disp_name(_UNIT_KEYS[uid])
        if uid in _UNIT_OFF:
            print(f"{GRAY}- {name}  (off){RST}")
        else:
            print(f"{GREEN}+{RST} {name}  {GRAY}(on{', main' if uid == main else ''}){RST}")


def _cmd_img(rest: str) -> None:
    """img | img <name> [name ...]: list the imaginary units, or add units and switch existing ones on or off."""
    if not rest.strip():
        _list_units(); return
    keys = _names(rest, "Usage: img [name ...]   (name: one letter or _long_name_)")
    old_pb = _primary_bit()
    for key in keys:
        name = _disp_name(key)
        uid  = _UNIT_KEYS.index(key) if key in _UNIT_KEYS else None
        if uid is not None and uid in _UNIT_LIST and uid not in _UNIT_OFF:
            _UNIT_OFF.add(uid)
            print(f"{GRAY}- {name}  (unit off){RST}")
        else:
            why = _unit_clash(key)
            if why: print(_fmt_error(why)); continue
            if uid is not None and uid in _UNIT_LIST:
                _UNIT_OFF.discard(uid)
                print(f"{GREEN}+ {name}{RST}  {GRAY}(unit on){RST}")
            else:
                _UNIT_LIST.append(_unit_id(key))
                print(f"{GREEN}+ {name}{RST}  {GRAY}(unit added){RST}")
        _unit_refresh()
    _unit_refresh(old_pb)


def _cmd_imgrm(rest: str) -> None:
    keys = _names(rest, "Usage: imgrm <name> [name ...]")
    old_pb = _primary_bit()
    for key in keys:
        uid = _UNIT_KEYS.index(key) if key in _UNIT_KEYS else None
        if uid is None or uid not in _UNIT_LIST:
            print(_fmt_error(f"Imaginary unit '{_disp_name(key)}' does not exist.")); continue
        _UNIT_LIST.remove(uid); _UNIT_OFF.discard(uid)
        print(f"{DEL}- {_disp_name(key)}{RST}  {GRAY}(unit removed){RST}")
        _unit_refresh()
    _unit_refresh(old_pb)


def _cmd_imgrmall() -> None:
    if not _UNIT_LIST: print(f"{GRAY}No imaginary units.{RST}"); return
    n, old_pb = len(_UNIT_LIST), _primary_bit()
    _UNIT_LIST.clear(); _UNIT_OFF.clear()
    _unit_refresh(old_pb)
    print(f"{DEL}- removed {n} unit{'s' if n != 1 else ''}{RST}")


_ASSIGN_RE = re.compile(_NAME_TOK_RE + r'\s*(?:\*\*|//|[+\-*/|])?=(?!=)')


def _split_items(rest: str) -> list:
    """'a=1 b=2' -> ['a=1', 'b=2']. An item runs until the next 'name=' or 'name OP=' that sits outside
    brackets and quotes, so values may contain spaces:  'a = 1 + 2 b = 3' -> ['a = 1 + 2', 'b = 3']."""
    starts, depth, quote = [0], 0, False
    for i, ch in enumerate(rest):
        if quote:
            quote = ch != '"'
        elif ch == '"':
            quote = True
        elif ch in '([{':
            depth += 1
        elif ch in ')]}':
            depth = max(0, depth - 1)
        elif depth == 0 and i > 0 and (rest[i - 1].isspace() or rest[i - 1] == ',') and _ASSIGN_RE.match(rest, i):
            starts.append(i)
    ends = starts[1:] + [len(rest)]
    items = [rest[a:b].strip().rstrip(',').strip() for a, b in zip(starts, ends)]
    return [it for it in items if it]


def _split_name_value(rest: str):
    """'k', 'k 5', 'k=5' or 'k+=5' -> (name, operator or None, value text), or None if there is no valid name."""
    m = re.match(rf'^{_NAME_TOK_RE}\s*(\*\*|//|[+\-*/|])?=\s*(.*)$', rest)
    if m:
        return m.group(1), m.group(2), m.group(3).strip()
    m = re.match(rf'^{_NAME_TOK_RE}(?:\s+(.*))?$', rest)
    if m:
        return m.group(1), None, (m.group(2) or '').strip()
    return None


def _list_consts() -> None:
    if not _const_vars: print(f"{GRAY}No constants defined.{RST}"); return
    for key in sorted(_const_vars, key=_disp_name):
        print(f"{GREEN}+{RST} {_disp_name(key)} = {_fmt_result(_const_vars[key])}")


def _const_one(item: str) -> None:
    """name | name value | name=value | name OP= value"""
    parsed = _split_name_value(item)
    if parsed is None:
        print(_fmt_error(f"Usage: const [<name> [value] | <name>=<value> ...]   (name: one letter or _long_name_)\n"
                         f"[{item}]")); return
    name, op, val = parsed
    key = _const_key(name)
    if key is None:
        print(_fmt_error("Constant names are one letter or _long_name_.")); return
    if _unit_active_key(key):
        print(_fmt_error(f"'{_disp_name(key)}' is an imaginary unit \u2014 switch it off first: img {_disp_name(key)}")); return
    if not val:
        if op: print(_fmt_error(f"'{op}=' needs a value.")); return
        if key in _const_vars: print(_fmt_result(_const_vars[key]))
        else: print(_fmt_error(f"Constant '{_disp_name(key)}' does not exist."))
        return
    if op:
        if key not in _const_vars:
            print(_fmt_error(f"Constant '{_disp_name(key)}' does not exist.")); return
        val = f"({_disp_name(key)}){op}({val})"
    ev = _stored_value(val, "Constant")
    if ev is None: return
    if key in _const_vars and not op:
        if not _confirm(f"Constant '{_disp_name(key)}' = {_fmt_result(_const_vars[key])} exists. Override?"):
            print(f"{GRAY}Kept.{RST}"); return
    verb = "updated" if key in _const_vars else "added"
    _user_vars.pop(key, None)
    _const_vars[key] = ev
    _show_const_added(key, ev, verb)


def _cmd_const(rest: str) -> None:
    """const | const <name> | const <name> <value> | const <a>=<x> <b>=<y> ... | const <name> OP= <value>"""
    rest = rest.strip()
    if not rest:
        _list_consts(); return
    for item in _split_items(rest):
        _const_one(item)


def _cmd_constrm(rest: str) -> None:
    for key in _names(rest, "Usage: constrm <name> [name ...]"):
        if key not in _const_vars: print(_fmt_error(f"Constant '{_disp_name(key)}' does not exist.")); continue
        del _const_vars[key]
        print(f"{DEL}- {_disp_name(key)}{RST}  {GRAY}(constant removed){RST}")


def _cmd_constex(rest: str) -> None:
    keys = _names(rest, "Usage: constex <name> [name ...]")
    for key in keys:
        print(_Bool(key in _const_vars) if len(keys) == 1 else f"{_disp_name(key)}: {str(_Bool(key in _const_vars))}")


def _cmd_constin(rest: str) -> None:
    for key in _names(rest, "Usage: constin <name> [name ...]"):
        if key not in _const_vars: print(_fmt_error(f"Constant '{_disp_name(key)}' does not exist.")); continue
        v = _const_vars[key]
        kind = ('function' if isinstance(v, Lambda) else 'set' if isinstance(v, SetObj)
                else 'complex' if isinstance(v, _CPLX) else 'number')
        print(f"{_disp_name(key)}  {GRAY}type:{RST} {kind}  {GRAY}value:{RST} {_fmt_result(v)}")


def _cmd_constrmall() -> None:
    if not _const_vars: print(f"{GRAY}No constants defined.{RST}"); return
    n = len(_const_vars)
    _const_vars.clear()
    print(f"{DEL}- removed {n} constant{'s' if n != 1 else ''}{RST}")


def _var_one(item: str) -> None:
    """name | name value | name=value | name OP= value"""
    parsed = _split_name_value(item)
    if parsed is None:
        print(_fmt_error(f"Usage: var [<name> [value] | <name>=<value> ...]   (name: one letter or _long_name_)\n"
                         f"[{item}]")); return
    name, op, val = parsed
    key = _const_key(name)
    if key is None:
        print(_fmt_error("Variable names are one letter or _long_name_.")); return
    if _unit_active_key(key):
        print(_fmt_error(f"'{_disp_name(key)}' is an imaginary unit \u2014 switch it off first: img {_disp_name(key)}")); return
    if key in _const_vars:
        print(_fmt_error(f"'{_disp_name(key)}' is a constant \u2014 change it with: const {_disp_name(key)} <value>")); return
    if not val:
        if op: print(_fmt_error(f"'{op}=' needs a value.")); return
        if key in _user_vars: print(_fmt_result(_user_vars[key]))
        else: print(_fmt_error(f"Variable '{_disp_name(key)}' does not exist."))
        return
    if op:
        if key not in _user_vars:
            print(_fmt_error(f"Variable '{_disp_name(key)}' does not exist.")); return
        val = f"({_disp_name(key)}){op}({val})"
    ev = _stored_value(val, "Variable")
    if ev is None: return
    verb = "updated" if key in _user_vars else "added"
    _user_vars[key] = ev
    print(f"{GREEN}+ {_disp_name(key)}{RST} = {_fmt_result(ev)}  {GRAY}(variable {verb}){RST}")


def _cmd_var(rest: str) -> None:
    """var | var <name> | var <name> <value> | var <a>=<x> <b>=<y> ... | var <name> OP= <value>"""
    rest = rest.strip()
    if not rest:
        if not _user_vars: print(f"{GRAY}No variables stored.{RST}"); return
        for key in sorted(_user_vars, key=_disp_name):
            print(f"{GREEN}+{RST} {_disp_name(key)} = {_fmt_result(_user_vars[key])}")
        return
    for item in _split_items(rest):
        _var_one(item)


def _cmd_varrm(rest: str) -> None:
    for key in _names(rest, "Usage: varrm <name> [name ...]"):
        if key in _const_vars:
            print(_fmt_error(f"'{_disp_name(key)}' is a constant \u2014 remove it with: constrm {_disp_name(key)}")); continue
        if key not in _user_vars: print(_fmt_error(f"Variable '{_disp_name(key)}' does not exist.")); continue
        del _user_vars[key]
        print(f"{DEL}- {_disp_name(key)}{RST}  {GRAY}(variable removed){RST}")


def _cmd_varrmall() -> None:
    if not _user_vars: print(f"{GRAY}No variables stored.{RST}"); return
    n = len(_user_vars)
    _user_vars.clear()
    _last_lambda[0] = None
    print(f"{DEL}- removed {n} variable{'s' if n != 1 else ''}{RST}"
          f"{GRAY}{' (constants kept)' if _const_vars else ''}{RST}")


def _save_name(rest: str, usage: str):
    name = rest.strip()
    if not name or ' ' in name:
        print(_fmt_error(usage)); return None
    return name


def _cmd_save(rest: str, as_default: bool = False) -> None:
    name = _DEFAULT_SAVE if as_default and not rest.strip() else _save_name(rest, "Usage: save <name>")
    if name is None: return
    data = _read_saves()
    if name in data['saves'] and not _confirm(f"Save '{name}' exists. Overwrite?"):
        print(f"{GRAY}Kept.{RST}"); return
    data['saves'][name] = _snapshot()
    if as_default: data['default'] = name
    _write_saves(data)
    n = len(_user_vars) + len(_const_vars)
    tag = ' (default)' if as_default else ''
    print(f"{GREEN}saved{RST} '{name}'{tag}  {GRAY}({n} item{'s' if n != 1 else ''}){RST}")


def _cmd_savedefault(rest: str) -> None:
    if not rest.strip():
        _cmd_save('', as_default=True); return
    name = _save_name(rest, "Usage: savedefault [name]")
    if name is None: return
    data = _read_saves()
    if name not in data['saves']: print(_fmt_error(f"No save named '{name}'.")); return
    data['default'] = name; _write_saves(data)
    print(f"{GREEN}default{RST} save is now '{name}'  {GRAY}(loaded at startup){RST}")


def _cmd_load(rest: str, quiet: bool = False) -> None:
    name = _save_name(rest, "Usage: load <name>")
    if name is None: return
    data = _read_saves()
    if name not in data['saves']: print(_fmt_error(f"No save named '{name}'.")); return
    n = _restore(data['saves'][name])
    if not quiet: print(f"{GREEN}loaded{RST} '{name}'  {GRAY}({n} item{'s' if n != 1 else ''}){RST}")


def _cmd_saves() -> None:
    data = _read_saves()
    if not data['saves']: print(f"{GRAY}No saves yet.{RST}"); return
    for name in sorted(data['saves']):
        n = len(data['saves'][name].get('vars', {})) + len(data['saves'][name].get('consts', {}))
        print(f"{'*' if name == data['default'] else ' '} {name}  {GRAY}({n} items){RST}")


def _cmd_saverm(rest: str) -> None:
    name = _save_name(rest, "Usage: saverm <name>")
    if name is None: return
    data = _read_saves()
    if name not in data['saves']: print(_fmt_error(f"No save named '{name}'.")); return
    del data['saves'][name]
    if data['default'] == name: data['default'] = None
    _write_saves(data); print(f"{DEL}- removed save{RST} '{name}'")


def _cmd_savesrmall() -> None:
    data = _read_saves()
    if not data['saves']: print(f"{GRAY}No saves yet.{RST}"); return
    if not _confirm(f"Delete all {len(data['saves'])} saves?"): print(f"{GRAY}Kept.{RST}"); return
    data['saves'].clear(); data['default'] = None; _write_saves(data)
    print(f"{DEL}- removed all saves{RST}")


def _cmd_saveren(rest: str) -> None:
    parts = rest.split()
    if len(parts) != 2: print(_fmt_error("Usage: saveren <name> <new>")); return
    old, new = parts
    data = _read_saves()
    if old not in data['saves']: print(_fmt_error(f"No save named '{old}'.")); return
    if new in data['saves']: print(_fmt_error(f"A save named '{new}' already exists.")); return
    data['saves'][new] = data['saves'].pop(old)
    if data['default'] == old: data['default'] = new
    _write_saves(data); print(f"{GREEN}renamed{RST} '{old}' → '{new}'")


_COMMANDS = {
    'const':       lambda r: _cmd_const(r),
    'constrm':     lambda r: _cmd_constrm(r),
    'constex':     lambda r: _cmd_constex(r),
    'constin':     lambda r: _cmd_constin(r),
    'constrmall':  lambda r: _cmd_constrmall(),
    'img':         lambda r: _cmd_img(r),
    'imgrm':       lambda r: _cmd_imgrm(r),
    'imgrmall':    lambda r: _cmd_imgrmall(),
    'var':         lambda r: _cmd_var(r),
    'varrm':       lambda r: _cmd_varrm(r),
    'varrmall':    lambda r: _cmd_varrmall(),
    'save':        lambda r: _cmd_save(r),
    'savedefault': lambda r: _cmd_savedefault(r),
    'load':        lambda r: _cmd_load(r),
    'saves':       lambda r: _cmd_saves(),
    'saverm':      lambda r: _cmd_saverm(r),
    'savesrmall':  lambda r: _cmd_savesrmall(),
    'saveren':     lambda r: _cmd_saveren(r),
}


def actions(s: str) -> bool:
    global DISPLAY_PREC
    cmd = s.strip().lower()
    raw = s.strip()

    if cmd == 'help':
        hlp(); return True

    _first = raw.split(None, 1)
    if _first and _first[0].lower() in _COMMANDS:
        if _first[0].lower() == 'var' and len(_first) > 1 and _first[1].lstrip().startswith('('):
            return False
        try:
            _COMMANDS[_first[0].lower()](_first[1] if len(_first) > 1 else '')
        except CalcError as ex:
            print(_fmt_error(str(ex)))
        return True

    if cmd.startswith('prec'):
        parts = cmd.split()
        if len(parts) == 1:
            print(f"{GREEN}Display: {DISPLAY_PREC} digits  (internal: {ctx.prec}){RST}")
            return True
        if len(parts) >= 2:
            ev = _eval_arg(' '.join(raw.strip().split()[1:]))
            if ev is _ABORT: return True
            if not isinstance(ev, dec):
                print(ev if isinstance(ev, str) else _fmt_error("prec: numeric value required"))
                return True
            try: n = int(ev)
            except Exception:
                print(_fmt_error("prec: integer required")); return True
            if n < 1:
                print(_fmt_error("prec: must be ≥ 1")); return True
            old_dp = DISPLAY_PREC
            old_cp = ctx.prec
            old_md = mpmath.mp.dps
            DISPLAY_PREC  = n
            ctx.prec      = n + GUARD_DIGITS
            mpmath.mp.dps = n + GUARD_DIGITS + 5
            result = run(_repin_constants)
            if result is _ABORT or result is _BACK:
                DISPLAY_PREC  = old_dp
                ctx.prec      = old_cp
                mpmath.mp.dps = old_md
                _repin_constants()
                return True
            print(f"{GREEN}Precision → {DISPLAY_PREC} display  ({ctx.prec} internal){RST}")
            return True
        print(_fmt_error("Usage: prec  or  prec <n>")); return True

    return False


def hlp():
    avf = ", ".join(sorted([
        k + (('(' + ', '.join(str(p) for p in inspect.signature(v).parameters.values()) + ')')
             if callable(v) else '')
        for k, v in dco.items() if callable(v)
    ]))
    avc = ", ".join(sorted([
        k + (('(' + ', '.join(str(p) for p in inspect.signature(v).parameters.values()) + ')')
             if callable(v) else '')
        for k, v in dco.items() if not callable(v)
    ]))
    print(f"""
{BOLD}Quick reference:{RST}
  Commands:   help / new / back / prec <n> / img... / var... / const... / save... / load   (Ctrl+D quits)
  Operators:  + - * / ** // %     (^ is the same as **)
  Variables:  single letters, or a word in underscores like _speed_
  Subscript:  x[1] / _work_[0] / {{0,1}}[0]
  Inline:     x=0 sets a variable;  f="sin(x)"; f(rad(x))
  Strings:    [hello!] / p[[work]] / {{0,1[ is whole]}}[1]
  Sets:       {{1,2,3}} / {{>=0<20}} / {{<0,>0}}   (comma = union)""")
    print(f"\n{BOLD}Available functions:{RST}\n  {BRBL}{avf}{RST}\n")
    print(f"{BOLD}Available constants and other:{RST}\n  {BRBL}{avc}{RST}")
    print(f"""
{BOLD}Lambda functions:{RST}
  {GREEN}f="expr"       {RST}  store a symbolic function (quoted expression).
                   Params are the free variables in the expression.
                   Example:  f="sin(x)"
  {GREEN}f(val)         {RST}  evaluate Lambda f at val.  f(pi/2) → 1
  {GREEN}run(f, val[, val2…]){RST}
                   evaluate Lambda f at the given values (cycled across params if fewer
                   values than params). f may be omitted to reuse the last unassigned
                   Lambda result.  Example:  f="x+y"; run(f, 2, 3)   → 5

{BOLD}Symbolic differentiation:{RST}
  {GREEN}diff(f)        {RST}  symbolic derivative of Lambda f → returns Lambda
  {GREEN}diff(f, n)     {RST}  n-th order derivative
  {GREEN}1 + diff(f)    {RST}  arithmetic on Lambdas produces new Lambdas: "1 + cos(x)"
  {GREEN}g=diff(f)      {RST}  store derivative as Lambda g

{BOLD}Quantum / physics:{RST}
  {GREEN}anharmonic(n, c){RST} anharmonic oscillator  H=p²/2+x²/2+c·x⁴, n-th eigenvalue
  {GREEN}hydrogen_e(n)  {RST}  hydrogen E_n = −1/(2n²) in atomic units (Hartree)
  {GREEN}schrodinger(V, n, xmin, xmax, Npts=100){RST}
                   FD solution of [−½∂²/∂x²+V(x)]ψ=Eψ, n-th eigenvalue
                   V is a Lambda (quoted expression); its free variable is the coordinate.
                   Example:  schrodinger("x**2/2", 0, -8, 8)    →  ~0.5 (HO ground)

{BOLD}Numerical integration:{RST}
  {GREEN}integrate(f, a, b){RST}
                   ∫_a^b f  (adaptive quadrature, arbitrary precision)
                   f is a Lambda (quoted expression); its free variable is the integration variable.
                   Example:  integrate("sin(x)", 0, pi)       → 2
                   Example:  integrate("exp(-x**2)", -inf, inf)   → √π

{BOLD}Comparison and logic:{RST}
  {GREEN}== != < > <= >={RST}   compare numbers, strings, functions, sets (sets: < <= > >= mean subset/superset)
  {GREEN}a ~= b        {RST}  equal after rounding both sides to whole numbers
  {GREEN}!x            {RST}  not: true for 0, empty set/string, empty function
  {GREEN}(A):IF(c,..):(B){RST}  A if every condition is true, otherwise B

{BOLD}Assignment:{RST}
  {GREEN}x=..  x+=..  x-=..  x*=..  x/=..  x//=..  x**=..  x|=..{RST}   work on numbers, functions and sets
  {GREEN}{{0}}+1 → {{0,1}}{RST}   on a finite set + and - add/remove a member; * / // ** map over members
  {GREEN}{{>0}}+1 → {{>1}}{RST}   on a continuous set the bounds shift/scale
  {GREEN}x[1]=2        {RST}  pin index 1 of set x:  x={{0}}; x[1]=2; x → {{0,[1]=2}}
  {GREEN}{{[10]=0,[[k]]=1}}{RST}  index/string-key entries in a literal (last duplicate wins)
  {GREEN}{{[*2]=>=0}}     {RST}  index rule: x[i] = i*2 ;  {{[+1]=>7}} → (i mod 7)+1  (N=0: no wrap)

{BOLD}Sets:{RST}
  {GREEN}range(a,b)    {RST}  continuous set {{>=a<b}};  {GREEN}~range(0,3){RST} → {{0,1,2}}
  {GREEN}~x            {RST}  round a number, or turn a set into its whole-number members

{BOLD}Loops (top-level calls):{RST}
  {GREEN}repeat(step, .., n){RST}   run every step n times. A step is  x=..  x+=..  x+=  or a bare
                   expression (its result goes to the first variable it mentions).
  {GREEN}until(step, .., cond){RST} same steps, stops once cond is true (checked after each tick).
                   Example:  x={{0,1}}; until(x+=, x[10]==10)     (aliases: rep, unt)

{BOLD}Variables{RST} (functions and sets you assign are kept automatically; numbers only with {GREEN}var{RST}):
  {GREEN}var x 5{RST} / {GREEN}var x=5{RST} / {GREEN}var x+=1{RST}   store or change a variable of any kind (no question asked)
  {GREEN}var a=1 b=2{RST}   several at once (the next {GREEN}name={RST} starts a new one; values may contain spaces)
  {GREEN}var x{RST} show   {GREEN}var{RST} list all   {GREEN}varrm x y{RST} remove   {GREEN}varrmall{RST} remove all (constants stay)

{BOLD}Constants:{RST}
  {GREEN}const x 5{RST} / {GREEN}const x=5{RST} / {GREEN}const x+=1{RST}   define, redefine (asks first) or update
  {GREEN}const a=1 b=2{RST}   several at once
  {GREEN}const x{RST} show   {GREEN}const{RST} list all   {GREEN}constrm x y{RST} remove   {GREEN}constex x{RST} exists?   {GREEN}constin x{RST} info
  {GREEN}constrmall{RST} remove all.  Constants are kept apart from variables: {GREEN}varrmall{RST} does not touch them.

{BOLD}Imaginary units:{RST}
  {GREEN}img{RST}            list the units (the first one that is on is the {BOLD}main{RST} unit: sqrt(-4) uses it)
  {GREEN}img j k{RST}        add units (a letter or a _long_name_); a unit you already have is switched on or off
  {GREEN}imgrm j k{RST}      remove units    {GREEN}imgrmall{RST}   remove all units ({GREEN}i{RST} too)
  Every unit squares to -1 and different units are independent, so  (1+2i+3j)*(1-j)  keeps both parts.
  Mixed products such as i*j are a part of their own and square to +1.  + - * / and whole-number powers
  work with any mix of units; sqrt, sin, abs, non-whole powers... take one unit at a time.
  A real negative root gives the main unit:  sqrt(-4) → 2i

{BOLD}Saves{RST} (file: ./calculator_saves.json in the current directory, created on the first save; or $CALC_SAVES):
  {GREEN}save n{RST}  {GREEN}load n{RST}  {GREEN}saves{RST}  {GREEN}saverm n{RST}  {GREEN}savesrmall{RST}  {GREEN}saveren n new{RST}
  {GREEN}savedefault [n]{RST}   make save n (or a fresh 'default' snapshot) load at startup
  Set NO_COLOR=1 to turn colors off.  Command-line options (--pipe, --no-prompt, ...): run with --help.
""")


# EXPRESSION ENGINE


_SLOW_AFTER = 4
_speed_tip_shown = [False]


def _speed_tip() -> None:
    if not _speed_tip_shown[0]:
        _speed_tip_shown[0] = True
        print(f"{YELLOW}Speed tip: install gmpy2{RST}")


def run(func, *args, **kwargs):
    timer = None
    if mpmath.libmp.BACKEND == 'python' and not _speed_tip_shown[0]:
        timer = threading.Timer(_SLOW_AFTER, _speed_tip)
        timer.daemon = True
        timer.start()
    try:
        return func(*args, **kwargs)
    except KeyboardInterrupt:
        print(f"{YELLOW}Interrupted.{RST}")
        return _BACK
    finally:
        if timer is not None:
            timer.cancel()


def _split_top_level(s: str, sep: str) -> list:
    parts, current, depth = [], '', 0
    in_str = False; str_char = ''
    for ch in s:
        if in_str:
            current += ch
            if ch == str_char: in_str = False
        elif ch in ('"', "'"):
            in_str = True; str_char = ch; current += ch
        elif ch in ('(', '[', '{'):
            depth += 1; current += ch
        elif ch in (')', ']', '}'):
            depth -= 1; current += ch
        elif ch == sep and depth == 0:
            parts.append(current); current = ''
        else:
            current += ch
    parts.append(current)
    return parts


def _apply_pipes(tokens: list) -> list:
    n = len(tokens)
    is_pipe = [t.type == tokenize.OP and t.string == '|' for t in tokens]
    if not any(is_pipe):
        return tokens

    roles = [None] * n
    prev_kind = None
    stack = 0
    for idx, t in enumerate(tokens):
        if is_pipe[idx]:
            if prev_kind in (None, 'op'):
                roles[idx] = 'open'
                stack += 1
                prev_kind = 'op'
            elif stack > 0:
                roles[idx] = 'close'
                stack -= 1
                prev_kind = 'value'
            else:
                roles[idx] = 'open'
                stack += 1
                prev_kind = 'op'
        else:
            if t.type in (tokenize.NUMBER, _TOK_STRING, _TOK_SFSTRING) or t.string in (')', ']', '}'):
                prev_kind = 'value'
            elif t.type == tokenize.NAME:
                prev_kind = 'value'
            else:
                prev_kind = 'op'

    if stack != 0:
        return tokens

    out = []
    for idx, t in enumerate(tokens):
        if is_pipe[idx]:
            if roles[idx] == 'open':
                out.append(Tok(tokenize.NAME, 'abs'))
                out.append(Tok(tokenize.OP, '('))
            else:
                out.append(Tok(tokenize.OP, ')'))
        else:
            out.append(t)
    return out


def get_clean_tokens(s: str) -> list:
    s = re.sub(r':\s*[iI][fF]\s*\(', ':tif(', s)
    s = _preprocess_set_anchors(s)
    s = _preprocess_lv(s)
    s = re.sub(r'(\d)(_[A-Za-z])', r'\1 \2', s)
    raw_tokens = []
    try:
        gen = tokenize.tokenize(io.BytesIO(s.encode('utf-8')).readline)
        for t in gen:

            if t.type == tokenize.STRING:
                inner = t.string[1:-1]
                raw_tokens.append(Tok(_TOK_STRING, inner))
                continue

            if t.type not in (tokenize.NUMBER, tokenize.NAME, tokenize.OP):
                continue

            if (t.type == tokenize.NUMBER and t.string.lower().endswith('j')
                    and (not IMG or _unit_active_key(t.string[-1]))):
                coeff = t.string[:-1]
                if coeff:
                    raw_tokens.append(Tok(tokenize.NUMBER, coeff))
                raw_tokens.append(Tok(tokenize.NAME, t.string[-1]))
                continue

            if t.type == tokenize.NAME:
                if _is_longvar(t.string):
                    raw_tokens.append(Tok(t.type, t.string))
                    continue
                if _is_sfstr(t.string):
                    raw_tokens.append(Tok(_TOK_SFSTRING, t.string))
                    continue
                if t.string not in dco:
                    has_digit = any(c.isdigit() for c in t.string)
                    if has_digit:
                        raw_tokens.extend(_split_alnum(t.string))
                        continue
                    if len(t.string) > 1:
                        raw_tokens.extend(_greedy_name(t.string))
                        continue
                elif _should_split(t.string):
                    raw_tokens.extend(_split_alnum(t.string))
                    continue

            raw_tokens.append(Tok(t.type, t.string))

    except tokenize.TokenError:
        pass

    expanded = []
    for idx, tok in enumerate(raw_tokens):
        if (tok.type == tokenize.NAME and
                tok.string in dco and
                callable(dco[tok.string]) and
                not _is_longvar(tok.string) and
                (idx + 1 >= len(raw_tokens) or raw_tokens[idx + 1].string != '(')):
            for ch in tok.string:
                expanded.append(Tok(tokenize.NAME, ch))
        else:
            expanded.append(tok)
    raw_tokens = expanded

    merged = []
    i = 0
    while i < len(raw_tokens):
        t0 = raw_tokens[i]
        if (i + 2 < len(raw_tokens)
                and t0.type == tokenize.NUMBER
                and raw_tokens[i+1].type == tokenize.OP
                and raw_tokens[i+1].string == '.'
                and raw_tokens[i+2].type == tokenize.NUMBER
                and '.' not in t0.string
                and '.' not in raw_tokens[i+2].string):
            merged.append(Tok(tokenize.NUMBER, t0.string + '.' + raw_tokens[i+2].string))
            i += 3
        elif (i + 1 < len(raw_tokens)
                and t0.type == tokenize.NUMBER
                and raw_tokens[i+1].type == tokenize.NUMBER
                and raw_tokens[i+1].string.startswith('.')
                and '.' not in t0.string):
            merged.append(Tok(tokenize.NUMBER, t0.string + raw_tokens[i+1].string))
            i += 2
        else:
            merged.append(t0)
            i += 1
    return _apply_pipes(merged)


_SYMBOL_MAP = {'\u2212': '-', '\u2013': '-', '\u00d7': '*', '\u22c5': '*', '\u00b7': '*', '\u00f7': '/', '\u2215': '/',
               '\u00a0': ' ', '\u2009': ' ', '\u202f': ' ', '\u03c0': 'pi', '\u00b2': '**2', '\u00b3': '**3'}


def _strip_spaces(s: str) -> str:
    buf = []
    in_str = False; str_char = ''
    last_was_callable = False
    prev_was_alnum = False
    run_is_name = False
    cur_run = ''
    paren_names = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch in _SYMBOL_MAP:
            s = s[:i] + _SYMBOL_MAP[ch] + s[i + 1:]
            ch = s[i]
        if in_str:
            buf.append(ch)
            if ch == str_char: in_str = False
            last_was_callable = True; prev_was_alnum = False; i += 1
        elif ch in ('"', "'"):
            in_str = True; str_char = ch; buf.append(ch)
            last_was_callable = False; prev_was_alnum = False; i += 1
        elif ch == '_':
            j = s.find('_', i + 1)
            if j > i:
                buf.append(_register_longvar(s[i+1:j]))
                last_was_callable = True; prev_was_alnum = False; i = j + 1
            else:
                buf.append('_'); last_was_callable = False; prev_was_alnum = False; i += 1
        elif ch == '[':
            if last_was_callable:
                buf.append(ch); last_was_callable = False; prev_was_alnum = False; i += 1
            else:
                depth = 1; j = i + 1
                while j < len(s) and depth > 0:
                    if s[j] == '[': depth += 1
                    elif s[j] == ']': depth -= 1
                    j += 1
                if depth > 0:
                    raise CalcError("Unclosed '['.")
                is_index_def = j < len(s) and s[j] == '=' and not (j + 1 < len(s) and s[j+1] == '=')
                if is_index_def:
                    buf.append(ch); last_was_callable = False; prev_was_alnum = False; i += 1
                else:
                    buf.append(' '); buf.append(_register_sfstr(s[i+1:j-1])); buf.append(' ')
                    last_was_callable = False; prev_was_alnum = False; i = j
        elif ch == '(':
            paren_names.append(cur_run if run_is_name else None)
            buf.append(ch); last_was_callable = False; prev_was_alnum = False; i += 1
        elif ch == ')':
            fname = paren_names.pop() if paren_names else None
            buf.append(ch)
            last_was_callable = fname in _SUBSCRIPTABLE_FNS
            prev_was_alnum = False; i += 1
        elif ch in (']', '}'):
            buf.append(ch); last_was_callable = True; prev_was_alnum = False; i += 1
        elif ch.isalnum():
            if not prev_was_alnum:
                run_is_name = ch.isalpha()
                cur_run = ''
            cur_run += ch
            buf.append(ch)
            last_was_callable = run_is_name
            prev_was_alnum = True
            i += 1
        elif ch != ' ':
            buf.append(ch); last_was_callable = False; prev_was_alnum = False; i += 1
        else:
            last_was_callable = False; prev_was_alnum = False; i += 1
    return re.sub(r'(XLONGx\d+x)(\d)', r'\1*\2', ''.join(buf))


_SUBSCRIPTABLE_FNS = {'zeros', 'range', 'interval'}


def _tok_text(t):
    if t.type == tokenize.NUMBER:
        if t.string.lower().endswith('j'):
            coeff = t.string[:-1] or '1'
            return f'mpmath.mpc(0, mpmath.mpf("{coeff}"))'
        low = t.string.lower()
        if low.startswith('0b') or low.startswith('0o') or low.startswith('0x'):
            return f'dec({t.string})'
        return f'dec("{t.string}")'
    if t.type == _TOK_STRING:
        safe = t.string.replace('\\', '\\\\').replace('"', '\\"')
        return f'Lambda("{safe}")'
    if t.type == _TOK_SFSTRING:
        safe = _sfstr_inner(t.string).replace('\\', '\\\\').replace('"', '\\"')
        return f'"{safe}"'
    return '**' if t.string == '^' else t.string


def _needs_mul(prev, curr, prev_name, v_dict):
    if prev.type == tokenize.NUMBER and curr.type == tokenize.NUMBER:
        raise CalcError(f"Invalid number '{prev.string}{curr.string}'.")
    prev_is_value  = prev.type in (tokenize.NUMBER, _TOK_STRING) or prev.string in (')', ']', '}')
    prev_is_name   = prev.type == tokenize.NAME
    prev_is_sfstr  = prev.type == _TOK_SFSTRING
    curr_is_value  = curr.type in (tokenize.NUMBER, _TOK_STRING) or curr.string in ('(', '{')
    curr_is_name   = curr.type == tokenize.NAME
    curr_is_string = curr.type == _TOK_STRING
    curr_is_sfstr  = curr.type == _TOK_SFSTRING

    insert = (
        (prev_is_value and curr_is_name) or
        (prev_is_name  and curr_is_value) or
        (prev_is_name  and curr_is_name) or
        (prev_is_value and curr_is_string) or
        (prev_is_value and curr_is_value) or
        (prev_is_sfstr and (curr_is_value or curr_is_name or curr_is_sfstr)) or
        ((prev_is_value or prev_is_name) and curr_is_sfstr)
    )
    if insert and curr.string == '(' and prev_is_name:
        if callable(dco.get(prev_name)):
            insert = False
        elif isinstance(v_dict.get(prev_name), Lambda):
            insert = False
    return insert


def _is_naked(prev_last, curr_first, v_dict):
    if curr_first.string not in ('(', '[', '{'):
        return False
    if prev_last.type != tokenize.NAME:
        return False
    return not _needs_mul(prev_last, curr_first, prev_last.string, v_dict)


def _split_args_top(tokens):
    args, cur, d = [], [], 0
    for t in tokens:
        if t.string in _CLOSERS: d += 1
        elif t.string in (')', ']', '}'): d -= 1
        if t.string == ',' and d == 0:
            args.append(cur); cur = []
        else:
            cur.append(t)
    args.append(cur)
    return args


_CLOSERS = {'(': ')', '[': ']', '{': '}'}


def _bracket_end(tokens, k, hi):
    """Index just past the bracket group opening at tokens[k]."""
    depth, j = 0, k
    while j < hi:
        sj = tokens[j].string
        if sj in _CLOSERS: depth += 1
        elif sj in (')', ']', '}'):
            depth -= 1
            if depth == 0: return j + 1
        j += 1
    return hi


_PREFIX_OPS = ('!', '~', '-', '+')


def _not_operand_end(tokens, k, hi, sym='!'):
    """End (exclusive) of the operand of a prefix operator whose operand starts at k."""
    while k < hi and tokens[k].string in _PREFIX_OPS:
        k += 1
    if k >= hi: return hi
    is_name = tokens[k].type == tokenize.NAME
    k = _bracket_end(tokens, k, hi) if tokens[k].string in _CLOSERS else k + 1
    while k < hi and (tokens[k].string == '[' or (is_name and tokens[k].string == '(')):
        k = _bracket_end(tokens, k, hi)
        is_name = False
    return k


def _rewrite_prefix(tokens, lo, hi, sym, fn, v_dict, in_subscript, in_str_call):
    """Rewrite each depth-0 prefix `sym` + operand into one synthetic fn(...) atom.
    Returns the new token list, or None if there was nothing to rewrite."""
    new, k, d, changed = [], lo, 0, False
    while k < hi:
        sk = tokens[k].string
        if sk in _CLOSERS: d += 1
        elif sk in (')', ']', '}'): d -= 1
        if sk == sym and d == 0:
            e = _not_operand_end(tokens, k + 1, hi, sym)
            op = tokens[k + 1:e]
            if not op:
                hint = " (for a factorial use fact(n))" if sym == '!' else ''
                raise CalcError(f"'{sym}' needs an operand after it{hint}.")
            new.append(Tok(tokenize.NAME, f"{fn}({_group_tokens(op, 0, len(op), v_dict, in_subscript, in_str_call)})"))
            k, changed = e, True
        else:
            new.append(tokens[k]); k += 1
    return new if changed else None


def _depth0(tokens: list, lo: int, hi: int):
    """Yield the index of every non-bracket token in [lo, hi) that sits outside all brackets."""
    depth = 0
    for k in range(lo, hi):
        s = tokens[k].string
        if s in _CLOSERS:
            depth += 1
        elif s in (')', ']', '}'):
            depth -= 1
        elif depth == 0:
            yield k


def _rewrite_special_syntax(tokens: list, lo: int, hi: int, v_dict: dict, in_subscript: bool, in_str_call: bool):
    """Rewrite (A):IF(c):(B), !x, a~=b and ~x into Python source; None if none applies."""
    def sub(toks):
        return _group_tokens(toks, 0, len(toks), v_dict, in_subscript, in_str_call)

    for k in _depth0(tokens, lo, hi):
        if k + 2 < hi and tokens[k].string == ':' and tokens[k + 1].string == 'tif' and tokens[k + 2].string == '(':
            cond_end = _bracket_end(tokens, k + 2, hi)
            if cond_end >= hi or tokens[cond_end].string != ':':
                raise CalcError("Ternary syntax is (A):IF(condition):(B).")
            then_t, cond_t, else_t = tokens[lo:k], tokens[k + 3:cond_end - 1], tokens[cond_end + 1:hi]
            if not then_t or not cond_t or not else_t:
                raise CalcError("Ternary syntax is (A):IF(condition):(B).")
            conds = ','.join(f"({_group_tokens(c, 0, len(c), v_dict)})" for c in _split_args_top(cond_t) if c)
            return f"(({sub(then_t)}) if _all_true({conds}) else ({sub(else_t)}))"

    rewritten = _rewrite_prefix(tokens, lo, hi, '!', '_not', v_dict, in_subscript, in_str_call)
    if rewritten is not None:
        return sub(rewritten)

    for k in _depth0(tokens, lo, hi):
        if k + 1 < hi and tokens[k].string == '~' and tokens[k + 1].string == '=':
            left, right = tokens[lo:k], tokens[k + 2:hi]
            if left and right:
                return f"_approx_eq(({sub(left)}),({sub(right)}))"

    rewritten = _rewrite_prefix(tokens, lo, hi, '~', '_round_obj', v_dict, in_subscript, in_str_call)
    if rewritten is not None:
        return sub(rewritten)
    return None


def _group_tokens(tokens: list, lo: int, hi: int, v_dict: dict, in_subscript: bool = False, in_str_call: bool = False) -> str:
    special = _rewrite_special_syntax(tokens, lo, hi, v_dict, in_subscript, in_str_call)
    if special is not None:
        return special
    atoms = []
    i = lo
    while i < hi:
        t = tokens[i]
        if t.string == '{':
            depth = 1
            j = i + 1
            while j < hi and depth > 0:
                if   tokens[j].string == '{': depth += 1
                elif tokens[j].string == '}':
                    depth -= 1
                    if depth == 0: break
                j += 1
            if depth != 0:
                raise CalcError("Unclosed '{'.")
            set_src = _build_set_source(tokens[i+1:j], v_dict)
            atoms.append((set_src, t, tokens[j]))
            i = j + 1
            continue
        if t.string in ('(', '['):
            open_ch  = t.string
            close_ch = ')' if open_ch == '(' else ']'
            depth = 1
            j = i + 1
            while j < hi and depth > 0:
                if   tokens[j].string == open_ch:  depth += 1
                elif tokens[j].string == close_ch: depth -= 1
                j += 1
            if depth > 0:
                raise CalcError(f"Unclosed '{open_ch}'.")
            if open_ch == '[' and i + 1 < j - 1 and tokens[i+1].string in _CMP_OPS:
                inner = _build_set_source(tokens[i+1:j-1], v_dict)
            else:
                child_in_str = in_str_call or (
                    open_ch == '(' and atoms and
                    atoms[-1][2].type == tokenize.NAME and
                    atoms[-1][2].string == 'str'
                )
                inner = _group_tokens(tokens, i + 1, j - 1, v_dict,
                                       in_subscript=(open_ch == '['),
                                       in_str_call=child_in_str)
            if open_ch == '(' and depth == 0 and not inner.strip() and not (atoms and atoms[-1][2].type == tokenize.NAME):
                raise CalcError("Empty parentheses.")
            atoms.append((open_ch + inner + close_ch, t, tokens[j - 1]))
            i = j
        else:
            atoms.append((_tok_text(t), t, t))
            i += 1

    folded = []
    ai = 0
    while ai < len(atoms):
        text, first_tok, last_tok = atoms[ai]
        if (first_tok is last_tok and first_tok.string in ('-', '+') and
                ai + 1 < len(atoms) and
                atoms[ai + 1][1].type == tokenize.NUMBER and
                not (ai + 2 < len(atoms) and atoms[ai + 2][1].string in ('**', '^')) and
                (ai == 0 or atoms[ai - 1][2].type == _TOK_SFSTRING)):
            sign = first_tok.string
            num_text, num_first, num_last = atoms[ai + 1]
            folded.append((f'(-{num_text})' if sign == '-' else num_text, num_first, num_last))
            ai += 2
            continue
        folded.append(atoms[ai])
        ai += 1
    atoms = folded

    pieces = []
    k = 0
    while k < len(atoms):
        chain = [atoms[k][0]]
        m = k
        while m + 1 < len(atoms):
            prev_last  = atoms[m][2]
            curr_first = atoms[m + 1][1]
            prev_name  = prev_last.string if prev_last.type == tokenize.NAME else None
            if not _needs_mul(prev_last, curr_first, prev_name, v_dict):
                break
            chain.append(atoms[m + 1][0])
            m += 1

        unsafe_start = k > 0 and _is_naked(atoms[k - 1][2], atoms[k][1], v_dict)
        unsafe_end   = (m + 1 < len(atoms) and
                        (_is_naked(atoms[m][2], atoms[m + 1][1], v_dict) or atoms[m + 1][1].string in ('**', '^')))

        if len(chain) > 1:
            has_sfstr_in_chain = any(
                atoms[k + j2][1].type == _TOK_SFSTRING
                for j2 in range(m - k + 1)
            )
            if has_sfstr_in_chain and in_str_call:
                args = []; num_group = []
                for j2 in range(m - k + 1):
                    if atoms[k + j2][1].type == _TOK_SFSTRING:
                        if num_group:
                            args.append('(' + '*'.join(num_group) + ')' if len(num_group) > 1 else num_group[0])
                            num_group = []
                        args.append(chain[j2])
                    else:
                        num_group.append(chain[j2])
                if num_group:
                    args.append('(' + '*'.join(num_group) + ')' if len(num_group) > 1 else num_group[0])
                pieces.append('str(' + ', '.join(args) + ')')
            elif has_sfstr_in_chain:
                num_group = [chain[j2] for j2 in range(m - k + 1)
                             if atoms[k + j2][1].type != _TOK_SFSTRING]
                if num_group:
                    pieces.append('(' + '*'.join(num_group) + ')' if len(num_group) > 1 else num_group[0])
                else:
                    pieces.append('""')
            elif not unsafe_start and not unsafe_end:
                pieces.append('(' + '*'.join(chain) + ')')
            else:
                pieces.append('*'.join(chain))
        else:
            pieces.append(chain[0])
        k = m + 1
    return ''.join(pieces)


class _OpRewriter(ast.NodeTransformer):
    """Route ** / // % through the calculator's own operator functions (precedence is already resolved by the parser)."""
    _CALLS = {ast.Pow: '_op_pow', ast.Div: '_op_truediv', ast.FloorDiv: '_op_floordiv', ast.Mod: '_op_mod'}

    def visit_BinOp(self, node):
        self.generic_visit(node)
        name = self._CALLS.get(type(node.op))
        if name is None:
            return node
        return ast.copy_location(ast.Call(func=ast.Name(id=name, ctx=ast.Load()), args=[node.left, node.right], keywords=[]), node)

    def visit_Compare(self, node):
        self.generic_visit(node)
        return ast.copy_location(ast.Call(func=ast.Name(id='_Bool', ctx=ast.Load()), args=[node], keywords=[]), node)


_code_cache: dict = {}


def _compile_source(src: str):
    code = _code_cache.get(src)
    if code is None:
        tree = ast.fix_missing_locations(_OpRewriter().visit(ast.parse(src, mode='eval')))
        code = compile(tree, '<expression>', 'eval')
        if len(_code_cache) > 4096:
            _code_cache.clear()
        _code_cache[src] = code
    return code


_EVAL_HELPERS = {
    '_Bool': _Bool,
    '_op_pow': _op_pow,
    '_op_truediv': _op_truediv,
    '_op_floordiv': _op_floordiv,
    '_op_mod': _op_mod,
    'mpmath': mpmath,
    'Lambda': Lambda,
    '_make_set_list': _make_set_list,
    '_make_set_ineq': _make_set_ineq,
    '_make_fmtval': _make_fmtval,
    '_apply_set_overrides': _apply_set_overrides,
    '_apply_set_modificators': _apply_set_modificators,
    '_approx_eq': _approx_eq,
    '_not': _not,
    '_round_obj': _round_obj,
    '_all_true': _all_true,
}


def _eval_env(v_dict: dict) -> dict:
    """Namespace for eval(): functions/constants, then the user's variables, then the helpers."""
    variables = {k: (dec(v) if isinstance(v, _DisplayDec) else v) for k, v in v_dict.items()}
    return {**dco, **variables, **_EVAL_HELPERS}


def cal(expr: str, v_dict: dict = None, chk: bool = False, nodisplay: bool = False, allow_inf: bool = False):
    if v_dict is None:
        v_dict = {}

    try:
        _am = _TOPLEVEL_ALIAS_RE.match(expr)
        if _am:
            expr = expr[:_am.start(1)] + _TOPLEVEL_CANON[_am.group(1)] + expr[_am.end(1):]
        if expr.strip().startswith('repeat(') and expr.strip().endswith(')'):
            return _eval_repeat(expr.strip(), v_dict, chk)
        if expr.strip().startswith('until(') and expr.strip().endswith(')'):
            return _eval_until(expr.strip(), v_dict, chk)
        if expr.strip().startswith('findroot(') and expr.strip().endswith(')'):
            return _eval_findroot(expr.strip(), v_dict, chk)

        tokens = get_clean_tokens(expr)
        if not tokens and expr.strip():
            return _fmt_error("The given expression has invalid syntax.\n")+_fmt_error_info(f"[{expr}]")
        tokens, _sfmt = _extract_format_sfstrings(tokens)
        if not nodisplay and not chk:
            _last_fmt_parts.clear(); _last_fmt_parts.extend(_sfmt)
        if not tokens:
            return _SFSTR_RESULT

        for idx in range(len(tokens) - 2):
            if (tokens[idx].type == tokenize.NAME and
                    tokens[idx+1].string == '[' and
                    tokens[idx+2].type == _TOK_STRING):
                return _fmt_error("The given expression has invalid syntax.\n")+_fmt_error_info(f"[{expr}]")

        env = _eval_env(v_dict)

        for idx in range(len(tokens) - 2):
            t0, t1, t2 = tokens[idx], tokens[idx+1], tokens[idx+2]
            if (t0.type == tokenize.NAME and t1.type == tokenize.OP and t1.string == '('
                    and t2.type == tokenize.OP and t2.string == ')'):
                target = env.get(t0.string)
                if target is not None and not callable(target):
                    if chk: return dec(1)
                    disp = _longvar_inner(t0.string) if _is_longvar(t0.string) else t0.string
                    return _fmt_error(f"'{disp}' is not a function.\n")+_fmt_error_info(f"[{expr}]")

        fin = _group_tokens(tokens, 0, len(tokens), v_dict)

        sub_bases = set()
        for k in v_dict:
            m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)\[.+\]$', str(k))
            if m:
                sub_bases.add(m.group(1))
        for _i2 in range(len(tokens) - 1):
            if (tokens[_i2].type == tokenize.NAME and
                    tokens[_i2].string not in dco and
                    tokens[_i2+1].string == '[' and
                    not isinstance(env.get(tokens[_i2].string), SetObj)):
                sub_bases.add(tokens[_i2].string)
        for base in sub_bases:
            env[base] = SubProxy(base, env, env.get(base))

        try:
            with decimal.localcontext(ctx) as _lctx:
                _lctx.traps[decimal.InvalidOperation] = False
                raw = eval(_compile_source(fin), {"__builtins__": {}}, env)

            if isinstance(raw, ImgNum):
                raw = _img_clean(raw)

            if isinstance(raw, (bool, _Bool)):
                return _Bool(raw)

            if isinstance(raw, Lambda):
                return raw

            if isinstance(raw, _MissingArgs):
                return raw

            if isinstance(raw, SetObj):
                return raw

            if isinstance(raw, str):
                if chk:
                    return dec(1)
                return raw

            if isinstance(raw, mpmath.mpc):
                im = dec(mpmath.nstr(raw.imag, mpmath.mp.dps))
                if abs(im) < dec('1e-' + str(ctx.prec - 2)):
                    return _display(dec(mpmath.nstr(raw.real, mpmath.mp.dps)))
                if chk:
                    return dec(1)
                if not IMG:
                    return _fmt_error("No real solutions.\n")+_fmt_error_info(f"[{fin}]")
                return raw

            if isinstance(raw, ImgNum):
                if chk:
                    return dec(1)
                return raw

            if isinstance(raw, mpmath.mpf):
                if mpmath.isinf(raw):
                    if chk: return dec(1)
                    if not allow_inf:
                        return ("inf" if raw > 0 else "-inf")
                if mpmath.isnan(raw):
                    if chk: return dec(1)
                raw = dec(mpmath.nstr(raw, mpmath.mp.dps))
            elif not isinstance(raw, dec):
                raw = dec(str(raw))
            if isinstance(raw, dec):
                if raw.is_infinite():
                    if chk: return dec(1)
                    if not allow_inf:
                        return ("inf" if raw > 0 else "-inf")
                if raw.is_nan():
                    if chk: return dec(1)
                    return ("nan")
            return raw if nodisplay else _display(raw)

        except SyntaxError as se:
            serr = str(se).splitlines()[0]
            return _fmt_error(f"Invalid syntax: {serr}\n")+_fmt_error_info(f"[{fin}]")
        except NameError as ne:
            if chk: return dec(1)
            name = getattr(ne, 'name', None) or (str(ne).split("'")[1] if "'" in str(ne) else "?")
            return _fmt_error(f"'{name}' is not defined.\n")+_fmt_error_info(f"[{fin}]")
        except TypeError as te:
            if chk: return dec(1)
            terr = _tidy_pyerror(str(te).splitlines()[0])
            return _fmt_error(f"Type error: {terr}\n")+_fmt_error_info(f"[{fin}]")
        except ZeroDivisionError:
            if chk: return dec(1)
            return _fmt_error("Division by zero.\n")+_fmt_error_info(f"[{fin}]")
        except decimal.Overflow:
            if chk: return dec(1)
            return _fmt_error("Result too large.\n")+_fmt_error_info(f"[{fin}]")
        except decimal.InvalidOperation:
            if chk: return dec(1)
            return _fmt_error("Invalid operation from input.\n")+_fmt_error_info(f"[{fin}]")
        except ValueError as ve:
            if chk: return dec(1)
            verr = _tidy_pyerror(str(ve).splitlines()[0])
            return _fmt_error(f"Value error: {verr}\n")+_fmt_error_info(f"[{fin}]")
        except OverflowError:
            if chk: return dec(1)
            return _fmt_error("Numerical overflow.\n")+_fmt_error_info(f"[{fin}]")
        except CalcError as ce:
            if chk: return dec(1)
            return _fmt_error(f"{ce}\n")+_fmt_error_info(f"[{fin}]")
        except Exception:
            if chk: return dec(1)
            raise

    except CalcError as ce:
        return _fmt_error(f"{ce}\n")+_fmt_error_info(f"[{expr}]")
    except Exception as e:
        return _fmt_error(f"Calculation problem: {_tidy_pyerror(str(e)) or type(e).__name__}\n")+_fmt_error_info(f"[{expr}]")


_INEQ_ASSIGN_RE = re.compile(r'^([A-Za-z]|XLONGx\d+x)((?:>=|<=|>|<).*)$')


def _parse_ineq_assignment(seg: str):
    m = _INEQ_ASSIGN_RE.match(seg)
    if not m:
        return None
    lhs, rest = m.group(1), m.group(2)
    if not _is_assign_target(lhs):
        return None
    return lhs, '{' + rest + '}'


_ASSIGN_OP_RE = re.compile(r'(\*\*|//|[+\-*/|])?=')


def _split_assign_seg(seg: str):
    """Split 'tgt[OP]=rhs' into (tgt, OP-or-None, rhs). Returns None if there's
    no real assignment '=' in seg (e.g. no '=' at all, or it's part of '==')."""
    m = _ASSIGN_OP_RE.search(seg)
    if not m:
        return None
    end = m.end()
    if end < len(seg) and seg[end] == '=':
        return None
    return ''.join(seg[:m.start()].split()), m.group(1), seg[end:]


def _parse_assignment(seg: str):
    split = _split_assign_seg(seg)
    if split is not None:
        lhs, op, rhs = split
        lhs, rhs = lhs.strip(), rhs.strip()
        if _is_assign_target(lhs):
            if op:
                if not rhs:
                    return None
                return lhs, f'({lhs}){op}({rhs})'
            return lhs, rhs
    return _parse_ineq_assignment(seg.strip())


def _assign_targets(inline_str: str) -> set:
    segs = _split_top_level(inline_str, ';') if ';' in inline_str else inline_str.split()
    targets = set()
    for seg in segs:
        if '=' not in seg:
            continue
        split = _split_assign_seg(seg)
        targets.add((split[0] if split is not None else seg.split('=', 1)[0]).strip())
    return targets


def sorta(s: str, allowed: list) -> list:
    if ';' in s:
        tokens = [seg for seg in _split_top_level(s, ';') if seg]
    else:
        tokens, current, depth = [], '', 0
        in_str = False; str_char = ''
        for ch in s:
            if in_str:
                current += ch
                if ch == str_char: in_str = False
            elif ch in ('"', "'"):
                in_str = True; str_char = ch; current += ch
            elif ch == '(':
                depth += 1; current += ch
            elif ch == ')':
                depth -= 1; current += ch
            elif ch == ' ' and depth == 0:
                if current: tokens.append(current)
                current = ''
            else:
                current += ch
        if current: tokens.append(current)

    pairs = []
    for p in tokens:
        split = _split_assign_seg(p)
        if split is not None:
            tgt, op, val = split
            tgt, val = tgt.strip(), val.strip()
            if tgt in allowed or _is_subscript_target(tgt):
                if op:
                    val = f'({tgt}){op}({val})'
                pairs.append((_normalize_sub_key(tgt), val))
        else:
            ineq = _parse_ineq_assignment(p.strip())
            if ineq and ineq[0] in allowed:
                pairs.append(ineq)

    n = len(pairs)
    dep_index = [[] for _ in range(n)]
    last_index_for_name = {}
    for i, (tgt, val) in enumerate(pairs):
        for name in allowed:
            if name not in val:
                continue
            if name == tgt:
                j = last_index_for_name.get(name)
            else:
                j = last_index_for_name.get(name)
                if j is None:
                    j = next((k for k, pr in enumerate(pairs) if pr[0] == name), None)
            if j is not None and j != i:
                dep_index[i].append(j)
        last_index_for_name[tgt] = i

    res, visited, active = [], [False] * n, [False] * n

    def visit(i):
        if visited[i] or active[i]: return
        active[i] = True
        for j in dep_index[i]:
            visit(j)
        active[i] = False; visited[i] = True
        res.append(pairs[i])
    for i in range(n):
        visit(i)
    return res


def split_inline(s: str):
    top = _split_top_level(s, ';')
    if len(top) > 1:
        segments = [seg.strip() for seg in top if seg.strip()]
        if len(segments) == 1:
            parsed = _parse_assignment(segments[0])
            if parsed:
                tgt, val = parsed
                return f"{tgt}={val};", ""
            return "", segments[0]
        if len(segments) >= 2:
            parsed = [_parse_assignment(seg) for seg in segments]
            last = _split_assign_seg(segments[-1])
            if all(parsed) and last is not None and _is_assign_target(last[0]):
                return ";".join(f"{t}={v}" for t, v in parsed) + ";", ""
            if all(parsed[:-1]):
                return ";".join(f"{t}={v}" for t, v in parsed[:-1]) + ";", segments[-1]
            return "", s.strip().replace(';', ' ')

    s_stripped = s.strip()
    if len(_split_top_level(s_stripped, ' ')) == 1:
        parsed = _parse_assignment(s_stripped)
        if parsed:
            tgt, val = parsed
            return f"{tgt}={val};", ""

    return "", s_stripped


def apply_inline(inline_str: str, all_vars: list, base: dict, isolate: bool, report: bool = False,
                 protect: set = None, fixed: set = None, track_resolved: list = None,
                 base_vals: dict = None) -> dict:
    work = base.copy() if isolate else base
    for tgt, val in sorta(inline_str, all_vars):
        if protect and tgt in protect:
            continue
        if fixed is not None and tgt in fixed:
            continue
        ev = run(cal, val, work, allow_inf=True, nodisplay=True)
        if ev is _ABORT or ev is _BACK: break
        if isinstance(ev, str) and _UNDEF_RE.search(ev):
            prev_len = len(track_resolved) if track_resolved is not None else 0
            ev = _resolve(val, work, track_resolved, keep_precision=True)
            if ev is _ABORT or ev is _BACK:
                break
            if isinstance(ev, (dec, Lambda)) and fixed is not None:
                fixed.add(tgt)
            if base_vals is not None and track_resolved is not None:
                for var in track_resolved[prev_len:]:
                    if var in work:
                        base_vals[var] = work[var]
        if isinstance(ev, _SFStrResult):
            _inline_error[0] = _fmt_error("Invalid operation from input.")
            break
        if isinstance(ev, (dec, Lambda, _CPLX, SetObj)):
            _store_assignment(work, tgt, ev)
        elif report:
            print(ev)
    return work if isolate else base


def _fmt_result(v):
    if isinstance(v, ImgNum):
        return _display_imgnum(v)
    if isinstance(v, mpmath.mpc):
        return _display_complex(v)
    if type(v) is dec:
        v = _display(v)
    return str(v)


def _fmt_element(v):
    if isinstance(v, _Bool):
        return str(v)
    if isinstance(v, dec):
        v = _display(v)
    return _fmt_result(v)


def _paint(res, text: str) -> str:
    """Color a formatted result by its type (theme: see the color constants at the top)."""
    if isinstance(res, _Bool):
        return f"{GREEN if res != 0 else YELLOW}{text}{RST}"
    if isinstance(res, SetObj):
        return VIOLET + re.sub(r'([{},])', lambda m: f"{GRAY}{m.group(1)}{VIOLET}", text) + RST
    if isinstance(res, Lambda):
        return f"{LSBL}{text}{RST}"
    if isinstance(res, _CPLX):
        return f"{BRBL}{text}{RST}"
    if isinstance(res, dec):
        return f"{WHITE}{text}{RST}"
    return text


def _print_result(res, assigned_set: set) -> None:
    if isinstance(res, _SFStrResult):
        print(_apply_sfstr_format(_last_fmt_parts, ""))
        return
    if isinstance(res, Lambda) and not assigned_set:
        _last_lambda[0] = res
    r = _fmt_result(res)
    if _is_error_text(r):
        print(r)
    else:
        print(_apply_sfstr_format(_last_fmt_parts, _paint(res, r)))


def _ask_value(name, cur_vars, depth=1):
    while True:
        disp = _longvar_inner(name) if _is_longvar(name) else name
        tag  = f"{RST}{GRAY}{depth}{RST}{BOLD}" if depth > 1 else ""
        try:
            inp = input(f"{BOLD}{disp}{tag}:{RST} ").strip()
        except KeyboardInterrupt:
            print(f'{GRAY}←{RST}')
            return _BACK
        if not inp: continue
        if actions(inp): continue
        if inp.lower() == 'new': return _ABORT
        if inp.lower() == 'back': return _BACK
        r = _resolve(inp, cur_vars, allow_inf=True, ask_name=name, ask_depth=depth, keep_precision=True)
        if r is _ABORT: return r
        if r is _BACK: continue
        if isinstance(r, (dec, Lambda, _CPLX)): return r
        print(r)


def _resolve(expr_str, cur_vars, resolved=None, allow_inf=False, ask_name=None, ask_depth=0, keep_precision=False):
    """Evaluate, asking for unknown variables. keep_precision=True is for values that get stored or reused;
    otherwise a plain number is rounded to the display precision."""
    ev = run(cal, expr_str, cur_vars, allow_inf=allow_inf, nodisplay=keep_precision)
    if ev is _ABORT or ev is _BACK: return ev
    for _ in range(20):
        if isinstance(ev, _MissingArgs):
            answers = []
            for param in ev.missing:
                if param in cur_vars and isinstance(cur_vars[param], (dec, Lambda, _CPLX)):
                    val = cur_vars[param]
                else:
                    depth = ask_depth + 1 if param == ask_name else 1
                    val = _ask_value(param, cur_vars, depth)
                    if val is _ABORT or val is _BACK: return val
                    cur_vars[param] = val
                    if resolved is not None and param not in resolved:
                        resolved.append(param)
                answers.append(val)
            ev = run(ev.lam, *ev.provided, *answers)
            if ev is _ABORT or ev is _BACK: return ev
            continue
        if isinstance(ev, str):
            m = _UNDEF_RE.search(ev)
            if m:
                name  = m.group(1)
                depth = ask_depth + 1 if name == ask_name else 1
                val = _ask_value(name, cur_vars, depth)
                if val is _ABORT or val is _BACK: return val
                cur_vars[name] = val
                if resolved is not None and name not in resolved:
                    resolved.append(name)
                ev = run(cal, expr_str, cur_vars, allow_inf=allow_inf, nodisplay=keep_precision)
                continue
        break
    if not keep_precision and type(ev) is dec:
        ev = _display(ev)
    return ev


def _eval_arg(s: str):
    cur = _stored()
    return _resolve(_strip_spaces(s), cur)


def _ask_loop(exp: str, all_vars: list, det_vars: list, inline_str: str,
              cur_vars: dict, assigned_set: set, fixed_inline: set,
              resolved_names: list, resolved_base_vals: dict):
    ask_items      = [('det', v) for v in det_vars if v not in cur_vars]
    ask_history    = []
    seen_sub       = set()
    asked_sub_keys = []
    broken         = False
    i = 0

    while True:
        for base, index_expr in get_sub_specs(exp):
            if isinstance(cur_vars.get(base), SetObj):
                continue
            idx = cal(index_expr, cur_vars)
            if not isinstance(idx, (dec, str)): continue
            key = _fmt_sub_key(base, idx)
            if key in seen_sub: continue
            seen_sub.add(key)
            if key in cur_vars: continue
            if key in _stored(): cur_vars[key] = _stored()[key]; continue
            ask_items.append(('sub', base, idx, key))

        if i >= len(ask_items): break

        item = ask_items[i]
        kind = item[0]
        if kind == 'det':
            v = item[1]
            if v in cur_vars: i += 1; continue
            prompt = f"{_longvar_inner(v) if _is_longvar(v) else v}:"
        else:
            _, base, idx, key = item
            if key in cur_vars: i += 1; continue
            key_disp = key[len(base):]
            prompt = f"{_longvar_inner(base) if _is_longvar(base) else base}{key_disp}:"

        go_back = go_retry = False
        ask_nm = key if kind == 'sub' else v
        while True:
            try:
                v_inp = input(f"{BOLD}{prompt}{RST} ").strip()
            except KeyboardInterrupt:
                print(f'{GRAY}←{RST}'); go_back = True; break
            if not v_inp: continue
            if actions(v_inp): continue
            if v_inp.lower() == 'new':  broken = True;    break
            if v_inp.lower() == 'back': go_back = True;   break
            ev = _resolve(v_inp, cur_vars, ask_name=ask_nm, ask_depth=1, keep_precision=True)
            if ev is _BACK:  go_retry = True; break
            if ev is _ABORT: broken = True;   break
            if kind == 'det':
                if isinstance(ev, (Lambda, SetObj)):
                    cur_vars[v] = ev; _persist(v, ev)
                elif isinstance(ev, (dec, _CPLX)):
                    cur_vars[v] = ev
                else:
                    print(ev); continue
                if inline_str:
                    cur_vars = apply_inline(inline_str, all_vars, cur_vars, ISO_INLINE,
                                            fixed=fixed_inline, track_resolved=resolved_names)
            else:
                cur_vars[key] = ev if isinstance(ev, (dec, _CPLX)) else dec(0)
                asked_sub_keys.append(key)
            ask_history.append(i); i += 1; break

        if broken: break
        if go_retry: continue
        if go_back:
            if ask_history:
                prev_i = ask_history.pop()
                prev   = ask_items[prev_i]
                if prev[0] == 'det':
                    cur_vars.pop(prev[1], None)
                else:
                    cur_vars.pop(prev[3], None)
                    seen_sub.discard(prev[3])
                    if prev[3] in asked_sub_keys: asked_sub_keys.remove(prev[3])
                i = prev_i
            else:
                broken = True; break

    return cur_vars, asked_sub_keys, broken


def _repeat_loop(exp: str, cur_vars: dict, resolved_names: list,
                 asked_sub_keys: list, det_vars: list, all_vars: list,
                 assigned_set: set, inline_str: str, already_set: set,
                 fixed_inline: set, resolved_base_vals: dict) -> None:
    _init_targets = (det_vars if det_vars else
                     (asked_sub_keys + resolved_names) if (asked_sub_keys or resolved_names) else
                     [v for v in all_vars if v not in already_set and v not in assigned_set])
    last_touched = _init_targets[-1] if _init_targets else None
    user_pinned  = set()

    while True:
        lbl = (f"{GRAY}{_longvar_inner(last_touched) if _is_longvar(last_touched) else last_touched}{RST}"
               if last_touched else "")
        try:
            inp = input(f"{lbl}{BRBL}{BOLD}>{RST} ").strip()
        except KeyboardInterrupt:
            print(f'{GRAY}←{RST}'); break
        if actions(inp): continue
        if inp.lower() in ('new', 'back'): break
        if not inp:
            res = _resolve(exp, cur_vars, resolved_names)
            if res is _ABORT or res is _BACK: break
            _print_result(res, assigned_set); continue

        inp = _strip_spaces(inp)
        just_set = user_updated = set()
        if '=' in inp or _INEQ_ASSIGN_RE.match(inp):
            assigns = sorta(inp, list(dict.fromkeys(all_vars + resolved_names)))
            if not assigns: continue
            err = abort = False; tmp = cur_vars.copy()
            for tgt, val in assigns:
                ev = _resolve(val, tmp, resolved_names, keep_precision=True)
                if ev is _ABORT or ev is _BACK: abort = True; break
                if isinstance(ev, (dec, Lambda, _CPLX, SetObj)):
                    tmp[tgt] = ev
                    if isinstance(ev, (Lambda, SetObj)): _persist(tgt, ev)
                else:
                    print(ev); err = True; break
            if abort: break
            if err: continue
            just_set     = {tgt for tgt, _ in assigns}
            user_updated = just_set.copy()
            user_pinned |= just_set
            cur_vars     = tmp
            last_touched = assigns[-1][0]
        else:
            ev = _resolve(inp, cur_vars, resolved_names, keep_precision=True)
            if ev is _ABORT: break
            if ev is _BACK: continue
            if isinstance(ev, (dec, _CPLX, Lambda, SetObj)) and last_touched is not None:
                cur_vars[last_touched] = ev
                user_updated = {last_touched}
            elif isinstance(ev, (dec, _CPLX, Lambda, SetObj)):
                print(_fmt_result(ev)); continue
            elif isinstance(ev, str):
                print(ev); continue
            else:
                _pending_expr[0] = inp; break

        if inline_str:
            for k, v in resolved_base_vals.items():
                if k not in user_updated and k not in user_pinned:
                    cur_vars[k] = v
            cur_vars = apply_inline(inline_str, all_vars, cur_vars, ISO_INLINE,
                                    protect=just_set | user_pinned)

        res = _resolve(exp, cur_vars, resolved_names)
        if res is _ABORT or res is _BACK: break
        _print_result(res, assigned_set)


def evaluate(raw: str) -> None:
    if actions(raw) or not raw or raw.lower() in ('new', 'back'): return

    try:
        raw = _strip_spaces(raw)
    except CalcError as ex:
        print(_fmt_error(str(ex)))
        return
    inline_str, exp = split_inline(raw)

    if not exp:
        if inline_str:
            all_vars = getv(raw)
            tmp      = _stored()
            shown    = False
            for tgt, val in sorta(inline_str, all_vars):
                ev = cal(val, tmp, nodisplay=True)
                if isinstance(ev, str):
                    print(ev)
                    shown = True
                    break
                m = _SET_INDEX_TGT_RE.match(tgt)
                base = m.group(1) if m and isinstance(tmp.get(m.group(1)), SetObj) else None
                if not (isinstance(ev, (Lambda, SetObj)) or base):
                    tmp[tgt] = ev
                    continue
                target = base or tgt
                if target in _const_vars:
                    name = _disp_name(target)
                    print(_fmt_error(f"'{name}' is a constant \u2014 change it with: const {name} <value>"))
                    shown = True
                    continue
                _store_assignment(tmp, tgt, ev)
                print(f"{_disp_name(target)} = {tmp[target]}")
                shown = True
            if not shown:
                print(_fmt_error("No expression found after assignments."))
        else:
            print(_fmt_error("No expression found after assignments."))
        return

    all_vars     = getv(raw)
    assigned_set = _assign_targets(inline_str)
    already_set  = set(_stored())
    det_vars     = [v for v in all_vars if v not in assigned_set and v not in already_set]

    cur_vars = _stored()
    probe    = cal(exp, {v: dec(0) for v in getv(exp)}, chk=True)
    if not isinstance(probe, dec):
        res = _resolve(exp, cur_vars)
        if res is _ABORT or res is _BACK: return
        _print_result(res, assigned_set)
        return

    cur_vars           = _stored()
    fixed_inline       = set()
    resolved_names     = []
    resolved_base_vals = {}

    if inline_str:
        cur_vars = apply_inline(inline_str, all_vars, cur_vars, ISO_INLINE,
                                fixed=fixed_inline, track_resolved=resolved_names,
                                base_vals=resolved_base_vals)

    if _inline_error[0]:
        print(_inline_error[0]); _inline_error[0] = None; return

    cur_vars, asked_sub_keys, broken = _ask_loop(
        exp, all_vars, det_vars, inline_str, cur_vars, assigned_set,
        fixed_inline, resolved_names, resolved_base_vals)

    if broken: return

    if inline_str:
        cur_vars = apply_inline(inline_str, all_vars, cur_vars, ISO_INLINE, fixed=fixed_inline)

    res = _resolve(exp, cur_vars, resolved_names)
    if res is _ABORT or res is _BACK: return
    _print_result(res, assigned_set)

    if NO_LOOP or (not det_vars and not resolved_names and not asked_sub_keys): return

    _repeat_loop(exp, cur_vars, resolved_names, asked_sub_keys, det_vars, all_vars,
                 assigned_set, inline_str, already_set, fixed_inline, resolved_base_vals)


# MAIN


class _UsageError(Exception):
    """A mistake on the command line."""


# option -> (key, takes a value)
_CLI_OPTIONS = {
    '--help': ('help', False),
    '--pipe': ('pipe', False), '--no-prompt': ('no_prompt', False),
    '--no-loop': ('no_loop', False), '--no-ask': ('no_ask', False),
    '--no-color': ('no_color', False), '--no-colors': ('no_color', False), '--color': ('color', False),
    '--no-default': ('no_default', False),
    '--prec': ('prec', True), '--set': ('set', True), '--const': ('const', True),
    '--load': ('load', True), '--saves': ('saves', True),
}


def _cli_help(prog: str) -> str:
    return f"""Usage: {prog} [options] [--] [expression ...]

Arbitrary-precision calculator. The expressions on the command line are evaluated first,
then you get the >> prompt (type help there for the syntax).  An argument is an option only
if it is listed below, so expressions such as -7//2 work as they are; -- ends the options.

Modes
  --pipe          script mode: also read expressions from standard input, one per line, and
                  print only the results. No prompt, no colors, no questions. Errors go to
                  standard error. Empty lines and lines starting with # are skipped.
  --no-prompt     evaluate the expressions on the command line, then exit (no >> prompt, and
                  no variable loop either; missing values are still asked for)
  --no-loop       after an answer, do not stay in the variable loop (the x> prompt)
  --no-ask        never ask for a missing value: it is an error instead (const replaces an
                  existing constant without asking). --pipe means --no-ask --no-loop.

Look
  --no-color, --no-colors   turn colors off (the NO_COLOR environment variable does too)
  --color                   force colors on, even when NO_COLOR is set. Without it colors are off
                            for --pipe, and for --no-prompt when the output is not a terminal.

Start-up
  --prec N        show N digits, like the prec command
  --set A=1       store a variable first, like the var command (--set "a=1 b=2" for several)
  --const A=1     store a constant first, like the const command (may be repeated too)
  --load NAME     load a save instead of the default one
  --no-default    do not load the default save
  --saves FILE    keep saves in FILE (the CALC_SAVES environment variable does too)

  --help          show this help and exit

Exit status: 0 on success, 1 if an expression or command failed (--pipe, --no-prompt),
2 for a mistake on the command line.

Examples
  {prog} "2(5)" "sqrt(2)"                 evaluate two expressions, then prompt
  {prog} --no-prompt "sin(pi/6)"          print 0.5 and exit
  echo "1/3" | {prog} --pipe --prec 10    print 0.3333333333
  {prog} --pipe --set x=4 < file.txt     evaluate every line of file.txt with x = 4
"""


def _parse_args(argv) -> dict:
    opts = {'help': False, 'pipe': False, 'no_prompt': False, 'no_loop': False, 'no_ask': False,
            'color': None, 'no_default': False, 'prec': None, 'set': [], 'const': [], 'load': None,
            'saves': None, 'exprs': []}
    i, only_exprs = 0, False
    while i < len(argv):
        a = argv[i]; i += 1
        if a == '--' and not only_exprs:
            only_exprs = True; continue
        is_opt = a in _CLI_OPTIONS or (a.startswith('--') and len(a) > 2 and a[2].isalpha())
        if only_exprs or not is_opt:
            opts['exprs'].append(a); continue
        name, eq, val = a.partition('=')
        spec = _CLI_OPTIONS.get(name)
        if spec is None:
            near = difflib.get_close_matches(name, [o for o in _CLI_OPTIONS if o.startswith('--')], n=1)
            raise _UsageError(f"unknown option '{name}'." + (f" Did you mean {near[0]}?" if near else ''))
        key, takes_value = spec
        if not takes_value:
            if eq: raise _UsageError(f"option '{name}' does not take a value.")
            if key == 'no_color':   opts['color'] = False
            elif key == 'color':    opts['color'] = True
            else:                   opts[key] = True
            continue
        if not eq:
            if i >= len(argv): raise _UsageError(f"option '{name}' needs a value.")
            val = argv[i]; i += 1
        if key in ('set', 'const'):
            if '=' not in val: raise _UsageError(f"option '{name}' needs NAME=VALUE, got '{val}'.")
            opts[key].append(val)
        elif key == 'prec':
            try: n = int(val)
            except ValueError: n = 0
            if n < 1: raise _UsageError(f"option '--prec' needs a whole number of at least 1, got '{val}'.")
            opts['prec'] = n
        else:
            opts[key] = val
    return opts


def _die(msg: str, status: int = 2) -> None:
    prog = os.path.basename(sys.argv[0]) if sys.argv and sys.argv[0] else 'calculator.py'
    sys.stderr.write(f"{prog}: {msg}\n")
    sys.exit(status)


def _cli_setup(fn, label: str) -> str:
    """Run a start-up step silently. A step that fails ends the program with status 2. Returns its output."""
    before = _ERROR_COUNT[0]
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            fn()
        except CalcError as ex:
            print(_fmt_error(str(ex)))
    text = _ANSI_RE.sub('', out.getvalue() + err.getvalue()).strip()
    if _ERROR_COUNT[0] != before:
        _die(f"{label}: {text}")
    return text


def _run_line(raw: str) -> None:
    try:
        evaluate(raw)
    except _AskDenied as ex:
        print(_fmt_error(str(ex)))


def _main(argv=None) -> None:
    global NO_ASK, NO_LOOP, _NO_COLOR
    argv = sys.argv[1:] if argv is None else argv
    try:
        opts = _parse_args(argv)
    except _UsageError as ex:
        prog = os.path.basename(sys.argv[0]) if sys.argv and sys.argv[0] else 'calculator.py'
        sys.stderr.write(f"{prog}: {ex}\nTry '{prog} --help'.\n")
        sys.exit(2)
    if opts['help']:
        _NO_COLOR = True
        print(_cli_help(os.path.basename(sys.argv[0]) if sys.argv and sys.argv[0] else 'calculator.py'))
        return

    pipe, once = opts['pipe'], opts['no_prompt']
    scripted   = pipe or once
    plain_out  = pipe or (once and not sys.stdout.isatty())      # scripted output should not carry color codes
    _NO_COLOR  = (plain_out or _NO_COLOR) if opts['color'] is None else not opts['color']
    NO_ASK     = opts['no_ask'] or pipe
    NO_LOOP    = opts['no_loop'] or scripted
    if opts['saves']:
        os.environ['CALC_SAVES'] = opts['saves']
    if pipe:
        try: sys.stdout.reconfigure(line_buffering=True)
        except (AttributeError, ValueError): pass

    # start-up steps: saves, precision, variables, constants (questions are answered "yes" here)
    ask_before, NO_ASK = NO_ASK, True
    if opts['load']:
        text = _cli_setup(lambda: _cmd_load(opts['load'], quiet=scripted), f"--load {opts['load']}")
        if text and not scripted: print(f"{GRAY}{text}{RST}")
    elif not opts['no_default']:
        _autoload_default(announce=not scripted)
    if opts['prec'] is not None:
        _cli_setup(lambda: actions(f"prec {opts['prec']}"), f"--prec {opts['prec']}")
    for item in opts['set']:
        _cli_setup(lambda: _cmd_var(item), f"--set {item}")
    for item in opts['const']:
        _cli_setup(lambda: _cmd_const(item), f"--const {item}")
    NO_ASK = ask_before
    _ERROR_COUNT[0] = 0
    _ERRORS_TO_STDERR[0] = scripted

    try:
        for arg in opts['exprs']:
            _run_line(arg.strip())
        if pipe:
            for line in sys.stdin:
                line = line.strip()
                if line and not line.startswith('#'):
                    _run_line(line)
        elif not once:
            while True:
                if _pending_expr[0] is not None:
                    raw = _pending_expr[0]; _pending_expr[0] = None
                else:
                    raw = builtins.input(_plain(f"{BRBL}{BOLD}>>{RST} ")).strip()
                if not raw or raw.lower() == 'new': continue
                _run_line(raw)
    except EOFError:
        print(_fmt_error("EOFError: Input stream interrupted."))
        sys.exit(1 if scripted else 0)
    except KeyboardInterrupt:
        print()
        if scripted: sys.exit(130)
    if scripted and _ERROR_COUNT[0]:
        sys.exit(1)


def main(argv=None) -> None:
    try:
        _main(argv)
    except BrokenPipeError:            # e.g. `... | head`: the reader went away, so stop quietly
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except (OSError, ValueError):
            pass
        sys.exit(1)


if __name__ == '__main__':
    main()
