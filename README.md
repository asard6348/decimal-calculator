# dcalc

`dcalc` is an interactive, arbitrary-precision mathematical REPL (Read-Eval-Print Loop)
built on Python and `mpmath`. It computes in decimal arithmetic and covers a range from
elementary calculations to symbolic differentiation, numerical integration and
computational physics.

## Features

- **Decimal arithmetic** – 50 digits of precision, `0.1+0.2` is `0.3`
- **Natural notation** – `2x**2+1`, `2(5)`, `2pi`, pasted `× ÷ π ²`
- **Missing variables are asked for** – `x*2+y` prompts for `x` and `y`, then
  allows changing them and showing the result again
- **Complex numbers** – `sqrt(-4)` is `2i`, with optional extra imaginary units (`j`, `k`, ...)
- **Calculus** – derivatives, integrals, limits, sums, roots
- **Symbolic algebra** – `sym on`: `(x^2-1)/(x-1)` is `x + 1`, unset variables stay in the answer; no extra packages
- **Functions and sets** – `f="x**2+3x"`, `{1,2,3}`, `{>=0<10}`
- **Saves** – variables, constants and functions can be saved and loaded
- **Scriptable** – `--pipe` reads expressions from stdin
- **Standalone executables** – no Python needed

## Download

Executables for Windows, Linux and macOS are on the
[Releases page](../../releases/latest).

| System | File | Run |
| --- | --- | --- |
| Windows 10 or 11 | `dcalc-windows-x64.exe` | `.\dcalc-windows-x64.exe` |
| Linux | `dcalc-linux-x64` | `chmod +x dcalc-linux-x64`, then `./dcalc-linux-x64` |
| macOS (Apple Silicon) | `dcalc-macos-arm64` | `chmod +x dcalc-macos-arm64`, `xattr -d com.apple.quarantine dcalc-macos-arm64`, then `./dcalc-macos-arm64` |

dcalc is a terminal program. Run it from a terminal (or PowerShell on Windows). On
Linux, double-clicking the file in a file manager does nothing visible, because no
terminal is attached and the program exits at once. To start it from a launcher,
create a `.desktop` file with `Terminal=true`:

```ini
[Desktop Entry]
Type=Application
Name=dcalc
Exec=/full/path/to/dcalc-linux-x64
Terminal=true
```

> Unsigned executables may trigger a SmartScreen or Gatekeeper warning.
> On Windows: **More info**, then **Run anyway**.

The file can be renamed to `dcalc` and put in a `PATH` directory. The name `dc` is
best avoided: it is a different program on most Linux and macOS systems.
Each release includes `SHA256SUMS.txt` with the checksums.

## Run from source

Python 3.9 or newer and mpmath are needed. gmpy2 is optional and can speed up
heavy calculations.

```bash
pip install mpmath
pip install gmpy2   # optional
python dcalc.py
```

## Getting started

The program shows a `>>` prompt. An expression is evaluated when Enter is pressed.
`help` prints the syntax and all functions. Ctrl+D quits (Windows: Ctrl+Z, then Enter).

Expressions can also be given as arguments. They are evaluated before the prompt:

```bash
python dcalc.py "2(5)" "sqrt(2)"
```

Below, `python dcalc.py` stands for the program. With an executable, its file name is used instead.

## The basics

```
2+3*4                             → 14
2**10                             → 1024
2^10                              → 1024
7//2                              → 3
-7//2                             → -4
-7%3                              → 2
1/3                               → 0.333333333333333333333333333333
0.1+0.2                           → 0.3
10**30+1                          → 1000000000000000000000000000001
1e3                               → 1000
0x10                              → 16
```

`^` and `**` both mean power. `//` and `%` round down, like in Python:
`-7//2` is `-4` and `-7%3` is `2`. Division by zero is an error.

Multiplication signs can be omitted:

```
2(5)                              → 10
(10/3)3                           → 10
2pi                               → 6.28318530717958647692528676656
x=3;2x**2+1                       → 19
```

A power binds tighter than implicit multiplication: `2x**2` is `2*(x**2)`.
Implicit multiplication binds tighter than division: `1/2x` is `1/(2x)`.
Brackets override both.

Complex numbers are built in, `i` being the imaginary unit. More units are described in
[Imaginary units](#imaginary-units).

```
sqrt(-4)                          → 2i
(1+2i)*(3-i)                      → 5+5i
abs(3+4i)                         → 5
```

Pasted text is accepted with these characters: `−` `×` `÷` `π` `²` `³`.

```
5−3                               → 2
2×3                               → 6
```

There is no `5!`, `fact(5)` is used instead.

## Variables

A variable is a single letter, or a word between underscores like `_speed_`.
An inline assignment is followed by `;` and the expression:

```
x=3;x^2                           → 9
_speed_=5;_speed_*2               → 10
```

An expression with an unset variable asks for it. The answer is followed by a loop
where the values can be changed and the result shown again:

```
>> x*2+y
x: 5
y: 1
11
y> 3
13
y> x=10
23
x> new
>>
```

In the loop:

- a number or expression changes the variable shown in the prompt
- `x=...` changes another variable
- an empty line shows the result again
- `new` or `back` leaves

A value typed at the prompt overrides an inline assignment. While the variables
are asked for, `back` returns to the previous question and `new` drops the expression.

A line that holds only assignments stores the variable for the session, whatever its
value is: a number, a complex number, a function, a set or text. The answer is the same
as `var` gives:

```
>> o=20
+ o = 20  (variable added)
>> o=i
+ o = i  (variable updated)
>> o='10'
+ o = "10"  (variable updated)
>> a=1;b=a+1
+ a = 1  (variable added)
+ b = 2  (variable added)
```

An assignment inside an expression (`x=3;x+1`) is only used by that expression; the
number is asked for again on the next line. Variables and constants stored with `var`
and `const` are remembered too. A constant, an active imaginary unit or an internal
constant or function (`e`, `pi`, `sin`, ...) cannot be assigned; the error says which it is.

Assignment operators: `+=` `-=` `*=` `/=` `//=` `**=` `|=`.

```
x=10;x//=3;x                      → 3
f="x";f+=1;f(5)                   → 6
```

## Functions

`help` lists every function. Common ones:

```
sqrt(2)                           → 1.41421356237309504880168872421
sin(pi/6)                         → 0.5
ln(e)                             → 1
log(100,10)                       → 2
log2(1024)                        → 10
exp(1)                            → 2.71828182845904523536028747135
fact(5)                           → 120
factorial(20)                     → 2432902008176640000
hypot(3,4)                        → 5
clamp(15,0,10)                    → 10
```

Trigonometry and its inverses (`sin`, `asin`, `sinh`, ...), `abs`, `floor`, `ceil`,
`round`, `sign`, `gamma`, `erf`, `zeta`, Bessel functions and more come from mpmath.

Statistics accept numbers or a set:

```
mean(1,2,3,4)                     → 2.5
median(5,1,3)                     → 3
std(2,4,4,4,5,5,7,9)              → 2
sum({1,2,3})                      → 6
max({4,9,2})                      → 9
```

Number theory:

```
gcd(12,18)                        → 6
lcm(4,6)                          → 12
isprime(97)                       → True
nextprime(100)                    → 101
primes(20)                        → {2,3,5,7,11,13,17,19}
divisors(28)                      → {1,2,4,7,14,28}
ncr(5,2)                          → 10
```

`size(3,4)` is the length of a vector. `len` counts the digits of a number, the
letters of a string or the items of a set.

```
size(3,4)                         → 5
len(12.34)                        → 4
```

Random numbers:

```
rand()                            → 0.0405648342555288823864623325831
randrange(10)                     → 3
randrange(5,10)                   → 7
randrange(0,10,2)                 → 6
randmatrix(2)                     → {{0.35684,0.96937},{0.92829,0.44172}}
randmatrix(2,3,10,20)             → {{12.13,15.80,13.45},{17.98,11.02,19.56}}
```

`rand()` is a number from 0 up to, but not including, 1. `randrange` works like Python's:
`randrange(stop)`, `randrange(start, stop)` or `randrange(start, stop, step)`, with whole numbers
only. `stop` is never returned, and an empty range is an error.

`randmatrix(m)` is a set of `m` rows with `m` random numbers each. `randmatrix(m,n)` has
`m` rows of `n` numbers, and `randmatrix(m,n,lo,hi)` takes the numbers from `lo` up to `hi`
instead of 0 to 1. A matrix is a set of sets, so a row or an item is reached with an index:

```
m=randmatrix(2,3);len(m)          → 2
m=randmatrix(2,3);len(m[0])       → 3
m=randmatrix(2);m[1][0]<1         → True
```

## Stored variables

`var` keeps a variable of any kind (number, function, set) for the session. A stored
variable is never asked for.

```
var k 1/3            store
var k=1/3            the same
var a=1 b=2          store several
var k                show
var k+=1             change (also *=, -=, ...)
var                  list all
varrm a b            remove one or more
varrmall             remove all variables (constants stay)
```

Several variables are stored as `name=value` pairs. A value may contain spaces, the
next `name=` starts the next item, and a later item can use an earlier one.
`const` works the same way.

```
>> var x=5 y=2+3
+ x = 5  (variable added)
+ y = 5  (variable added)
>> x*2+1
11
>> var x+=1 y*=2
+ x = 6  (variable updated)
+ y = 10  (variable updated)
>> var
+ x = 6
+ y = 10
```

Changing a variable asks nothing. `var` refuses the name of a constant (`const` is used
for those). `var(1,2,3)` is still the variance function.

Everything stored by a bare assignment (`o=5`, `f="x**2"`, `s={1,2}`) is a variable too: `var` lists it,
`varrm` and `varrmall` remove it.

## Constants

Built in: `pi`, `e`, `tau`, `phi`, `euler`, `catalan`, `sqrt2`, `sqrt3`, `ln2`, `ln10`,
`inf`, `ninf`, `nan`, `true`, `false`, and some physics ones: `light`, `planck`,
`boltzmann`, `avogadro`, `echarge`, `grav`, `gravity`, `hbar`.

```
tau                               → 6.28318530717958647692528676656
light                             → 299792458
```

Own constants last for the session, survive `varrmall`, and can be saved:

```
const k 1/3          define
const l=2 p=3        define several
const k              show
const k+=1           change (also *=, -=, ...)
const                list all
constrm k l          remove one or more
constex k            exists? (True/False)
constin k            type and value
constrmall           remove all
```

`const` asks before replacing an existing constant. `constrm`, `constex` and `constin`
accept several names; `constex` then prints `name: True` or `name: False` for each.

```
>> const l=20 p=30
+ l = 20  (constant added)
+ p = 30  (constant added)
>> l+p
50
>> const
+ l = 20
+ p = 30
```

## Defining functions

A function is a quoted expression. Its free variables are the parameters.

```
f="x**2+3x";f(2)                  → 10
f="x+y";run(f,2,3)                → 5
```

Functions support arithmetic: `f+g`, `f*2`, `f+=1`.

### Derivatives

`diff` returns a new function. Unknown functions are reported.

```
diff("sin(x)")                    → "cos(x)"
f="x**2+3x";diff(f)               → "2 * x + 3"
diff("x**3",2)                    → "6 * x"
```

### Integrals, limits, sums, roots

The variable is the free variable of the quoted expression.

```
integrate("sin(x)",0,pi)          → 2
integrate("exp(-x**2)",-inf,inf)  → 1.77245385090551602729816748334
limit("sin(x)/x",0)               → 1
nsum("1/x**2",1,inf)              → 1.64493406684822643647241516665
findroot("cos(x)-x",1)            → 0.739085133215160641655312087674
polyroots({1,-3,2})               → {1,2}
taylor("exp(x)",0,3)              → {1,1,0.5,0.166666666666666666666666666667}
```

`integrate` reports an error when the integral does not appear to converge. `limit`
and `nsum` use extrapolation: accurate for ordinary cases, not for very slow ones such
as `ln(x)/x` at infinity. Divergent sums such as `1/x` are not detected.

## Sets

```
{1,2,3}                           → {1,2,3}
{1,2,3}[1]                        → 2
{1,2,3}[4]                        → 2
```

Indexing starts at 0 and an index past the end wraps around.

On a finite set, `+` adds a member, `-` removes one, and `*`, `/`, `//`, `**` apply to
every member. `|` is union.

```
{0}+1                             → {0,1}
{1,2,3}-2                         → {1,3}
{1,2}*3                           → {3,6}
{1,2}|{2,3}                       → {1,2,3}
sort({3,1,2})                     → {1,2,3}
```

A set can also be a range, `{>=0<10}`, or two ranges, `{<0,>5}`. `+` and `*` shift or
scale the range.

```
{>0}+1                            → {>1}
{>=0<10}[5]                       → 5
~range(0,3)                       → {0,1,2}
~2.5                              → 2
```

`~` rounds: a number becomes a whole number, a set becomes its whole-number members.
Ties follow the [rounding mode](#rounding), as in `round`: half even by default, so `~2.5` is `2`.

Single indexes can have their own value, or a rule can cover all indexes:

```
x={0};x[3]=7;x                    → {0,[3]=7}
x={0};x[3]=7;x[3]                 → 7
x={[*2]=>=0};x[4]                 → 8
x={[+1]=>7};x[8]                  → 2
```

`{[*2]=>=0}` means index `i` gives `i*2`. In `{[+1]=>7}` the index wraps at 7 first,
so `i` gives `(i mod 7)+1`. With `>=0` the index is used as is.

Sets are compared with `<=` and `<` (subset).

```
{1,2}<={1,2,3}                    → True
len({1,2,3})                      → 3
```

## Comparing and deciding

```
5>3                               → True
1+1==2                            → True
2.4~=2                            → True
!0                                → True
(1):IF(2>1):(0)                   → 1
```

`==`, `!=`, `<`, `>`, `<=`, `>=` work on numbers, sets, strings and functions.
`~=` rounds both sides to whole numbers first (by the [rounding mode](#rounding)). `!` is not: true for 0, an empty set
and an empty string.

`(A):IF(c):(B)` gives `A` if the condition is true, otherwise `B`. Several conditions
can be separated by commas, all of them must be true.

## Repeating

`repeat` runs steps a number of times, `until` runs them until a condition is true.
A step is `x=...`, `x*=...`, or `x+=` alone, which adds 1 to a number or the next item
to a set of numbers.

```
x=1;repeat(x*=2,10)               → 1024
x=0;until(x+=,x>9)                → 10
x={0,1};until(x+=,x[10]==10)      → {0,1,2,3,4,5,6,7,8,9,10}
```

`until` stops after 100000 rounds.

## Text

Text goes between square brackets. Before an expression, it is printed ahead of the
result:

```
[total: ]2+2                      → total: 4
```

Text in square brackets can also be an index: `p[[work]]=5;p[[work]]`.

## Imaginary units

`i` is the default imaginary unit. More units can be added, each giving a number an
independent imaginary part. A unit is named by one letter or a word between underscores.

```
img                  list the units
img j k              add units; an existing unit is switched on or off
imgrm j k            remove units
imgrmall             remove all units, i too
```

```
>> img
+ i  (on, main)
>> img j k
+ j  (unit added)
+ k  (unit added)
>> img
+ i  (on, main)
+ j  (on)
+ k  (on)
>> (1+2j)*(3-j)
5+5j
>> (1+2i+3j)*(1-j)
4+2i+2j-2ij
>> (1+j)^2
2j
>> 1/j
-j
```

Each unit squares to -1 and different units stay independent: `i*j` is a separate
part, written `ij`, and it squares to +1.

```
>> i*j
ij
>> (i*j)^2
1
>> (i+j)*(i-j)
0
```

Brackets are multiplied out, and `+ - * /` and whole-number powers work with any mix
of units. Functions (`sqrt`, `exp`, `sin`, `abs`, `re`, `im`, non-whole powers, ...)
accept one unit at a time, since they are defined for ordinary complex numbers:
`a+b*u` with a single unit `u` is treated as `a+b*i`.

```
>> sqrt(3+4j)
2+j
>> abs(3+4j)
5
>> exp(j*pi)
-1
```

Two units in one function call, like `sin(i+j)`, are an error, and so is dividing by
a number without an inverse (like `1+i*j`).

### On, off and removed

`img` with an existing name switches that unit off, or on again. A unit that is off
stays listed, and its name is an ordinary name again. `imgrm` removes a unit from
the list.

```
>> img k
- k  (unit off)
>> img k
+ k  (unit on)
>> imgrm k
- k  (unit removed)
>> img
+ i  (on, main)
+ j  (on)
```

The first unit in the list that is on is the **main** unit. Real negative roots give
the main unit, so `sqrt(-4)` is `2i`. If `i` is switched off, `j` takes over. Stored
numbers keep their meaning.

```
>> sqrt(-4)
2i
>> img i
- i  (unit off)
>> sqrt(-4)
2j
>> img i
+ i  (unit on)
```

With no unit on, `sqrt(-4)` is an error. A unit name cannot be taken by a variable, a
constant or a built-in (`e`, `pi`, ...).

Units, their order and their on/off state are stored by `save`.

## Symbolic algebra

`sym` simplifies expressions exactly and keeps unset variables in the answer, so they
need no value. It is built in and needs nothing besides `mpmath`.

```
sym on               every expression is simplified symbolically
sym off              back to numbers (unset variables are asked for)
sym                  show the mode
sym <expression>     one expression, whatever the mode
sym <op> <expression>  one operation, see below
```

`--sym` starts with the mode on, and `save` stores it.

```
>> sym on
>> x*2+x
3x
>> (x^2-1)/(x-1)
x + 1
>> 1/x+1/(x+1)
(2x + 1)/(x*(x + 1))
>> 1-sin(x)^2
cos(x)^2
>> sqrt(8)+sqrt(2)+x
x + 3*sqrt(2)
>> 0.5*x
x/2
```

### Operations

| Command | Result |
| --- | --- |
| `sym simplify e` (or `sym e`) | a polynomial is multiplied out (`(a+b)^2` is `a^2 + 2a*b + b^2`, unless that gets very long, like `(x+1)^20`); a fraction gets the shortest of the factored, expanded and single-fraction forms |
| `sym expand e` | sum of terms: `(x+1)^2` is `x^2 + 2x + 1` |
| `sym factor e` | product of factors: `x^2*y-y` is `y*(x + 1)(x - 1)` |
| `sym cancel e` (`sym together e`, `sym frac e`) | one fraction in lowest terms |
| `sym apart e` | partial fractions: `1/(x^2-1)` is `1/(2(x - 1)) - 1/(2(x + 1))` |
| `func(a, b, ...)` | the expressions, added, as a quoted expression; simplified with `sym on` or after `sym`; see below |
| `sym collect x: e` | powers of `x` grouped: `a*x+b*x+x^2+c` is `x^2 + (a + b)*x + c` |

`apart` and `collect` take the variable in front, like `x: expr`; without it the only
variable (or the first one) is used. `apart` needs a denominator with one variable.

The operations are also functions, for use inside other expressions and for stored
functions: `simplify("(x^2-1)/(x-1)")`, `expand(f)`, `factor(f)`, `cancel(f)`,
`apart(f)`, `collect(f, "x")`, where `f` is a stored function or a text.

### Assignments after an operation

An operation in front of an assignment stores the result of that operation as a quoted
expression, so `sym cancel x=0.34` stores `x = "17/50"`. This works for every operation
(`sym expand w=(a+b)^2`, `sym factor v=a^2-b^2`, `sym collect x: t=a*x+b*x`) and for
several assignments in one line (`sym cancel p=0.5;r=p+1`). `sym` alone before an assignment
makes it symbolic, as in `sym h=(x+1)(x-1)`.

### frac: a number as a fraction

`frac(0.34)` is `"17/50"`: a quoted expression, so it can be assigned straight away,
`q=frac(0.75)`. A long decimal that is a rounded simple fraction (`frac(1/3)`) gives that
fraction; a number that is not close to a simple one (`frac(pi)`) is an error. `frac` of a
quoted expression is `cancel`. `sym frac x=0.34` and `sym cancel 0.34` do the same for
one value.

### func: an expression as a quoted expression

`func(a, b, ...)` returns its arguments as a quoted expression, without asking for any
variable, so the result can be assigned straight away. Several arguments are added
together. With `sym on`, and after `sym`, the result is simplified.

```
>> f=func(x*2+x)
+ f = "x*2+x"  (variable added)
>> sym on
>> f=func((a+b)^2)
+ f = "a^2 + 2a*b + b^2"  (variable added)
>> g=func((a+b)^2, a*b)
+ g = "a^2 + 3a*b + b^2"  (variable added)
>> sym off
>> sym f=func((a+b)^2)
+ f = "a^2 + 2a*b + b^2"  (variable updated)
```

`sym` in front of an assignment makes that one assignment symbolic, with or without
`func`: `sym h=(x+1)(x-1)` stores `"x^2 - 1"`.

### What it knows

- Polynomials and fractions of several variables, exactly: factoring over the integers,
  gcd, cancelling, rationalizing `1/(1+sqrt(2))`.
- Roots and powers: `sqrt(x)^2` is `x`, `sqrt(12)` is `2*sqrt(3)`, `e^x*e^y` is `exp(x + y)`.
- `sin`, `cos`, `sinh`, `cosh` identities (`sin(x)^2+cos(x)^2` is `1`), exact values
  at multiples of `pi/12`, parity (`sin(-x)` is `-sin(x)`), `asin(sin(pi/6))` style
  compositions, `ln` of rationals, `exp(ln(x))`, `abs` of products.
- `pi`, `e`, imaginary units and stored constants stay symbols.
- Other functions (`tan`, `gamma`, ...) are kept as they are, with simplified arguments.

An expression with no variables at all (`1/3`, `2pi`) is still a plain calculation and
prints a decimal in the mode; `sym 1/3` or `sym sqrt(8)` gives `1/3` and `2*sqrt(2)`.

Numbers are exact: `0.5` is `1/2`, and a long stored decimal is read as the simple
fraction it is close to. Unset variables are taken as real, so `sqrt(x^2)` is `abs(x)`
and `ln(exp(x))` is `x`. Roots of sums, like `sqrt(x+1)`, stay as they are.

### Assignment

In `sym` mode an assignment stores the simplified result as a function:

```
>> g=x*2+x
+ g = "3x"  (variable added)
>> g*2
6x
>> f=x^2+1
>> f(y+1)
y^2 + 2y + 2
```

A stored variable with a value wins over a symbol of the same name, so after `a=2`
the `a` in `a*x+x` is `2`. `varrm` it to make it a symbol again. Names of internal
functions and constants cannot be assigned.

### Limits

Expressions that `sym` does not handle (sets, comparisons, text, subscripts, ...) go
through the normal calculator, so turning the mode on never takes a feature away.
Factoring is given 3 seconds; on very large polynomials the factored form is skipped
and the expanded one is shown.

## Rounding

`round()`, `~` and `~=` all use one rounding mode. `rounding` shows it, `rounding <mode>` changes it.
The default is `half even`.

```
>> rounding
Rounding: half even
>> ~2.5
2
>> rounding half up
Rounding → half up
>> ~2.5
3
>> round(2.567,2)
2.57
```

| Mode | Rounds to |
| --- | --- |
| `half even` | the nearest whole number, a tie goes to the even one (default) |
| `half up` | the nearest whole number, a tie goes away from zero |
| `half down` | the nearest whole number, a tie goes toward zero |
| `up` | always away from zero |
| `down` | always toward zero |
| `05up` | away from zero if the last kept digit would be 0 or 5, otherwise toward zero |
| `floor` | toward −infinity |
| `ceiling` | toward +infinity |

The result for a few numbers:

| Mode | `~2.5` | `~3.5` | `~-2.5` | `~2.1` | `~-2.1` | `~5.1` |
| --- | --- | --- | --- | --- | --- | --- |
| `half even` | 2 | 4 | -2 | 2 | -2 | 5 |
| `half up` | 3 | 4 | -3 | 2 | -2 | 5 |
| `half down` | 2 | 3 | -2 | 2 | -2 | 5 |
| `up` | 3 | 4 | -3 | 3 | -3 | 6 |
| `down` | 2 | 3 | -2 | 2 | -2 | 5 |
| `05up` | 2 | 3 | -2 | 2 | -2 | 6 |
| `floor` | 2 | 3 | -3 | 2 | -3 | 5 |
| `ceiling` | 3 | 4 | -2 | 3 | -2 | 6 |

The mode applies to numbers, to complex numbers (each part) and to the members of a set.
The digits shown in an answer (`prec`) and the functions `floor`, `ceil` and `int` do not use it.
The mode is stored by `save`.

## Commands

| Command | Effect |
| --- | --- |
| `help` | syntax, features and all functions |
| `new` | leave the current question or loop |
| `back` | previous question |
| `prec 50` | display 50 digits (20 more are used internally), `prec` alone shows the setting |
| `rounding ...` | rounding mode of `round`, `~` and `~=`: `rounding`, `rounding half up`, ... see Rounding |
| `var ...` | variables: `var`, `varrm`, `varrmall` |
| `const ...` | constants: `const`, `constrm`, `constex`, `constin`, `constrmall` |
| `img ...` | imaginary units: `img`, `imgrm`, `imgrmall` |
| `sym ...` | symbolic algebra: `sym on`, `sym off`, `sym <expression>`, `sym factor ...`, see Symbolic algebra |
| `save`, `load`, ... | see Saving |

## Saving

```
save work            save variables, functions, sets, constants, imaginary units, the rounding mode and the sym mode
load work
saves                list, * marks the default one
saverm work          delete one
savesrmall           delete all
saveren work newname   rename
savedefault work     load this one at every start
savedefault          save the current state as "default" and load it at every start
```

Saves are written to `dcalc_saves.json` in the current directory, created on the first
save. `DCALC_SAVES` sets another path.

## Command line

```
python dcalc.py [options] [--] [expression ...]
```

Only the options below are options, so `-7//2` and `-h` are expressions. `--` ends the
options.

| Option | Effect |
| --- | --- |
| `--pipe` | read expressions from stdin, one per line (`#` lines and empty lines are skipped); print results only: no prompt, colors or questions, errors to stderr; implies `--no-ask` and `--no-loop` |
| `--no-prompt` | exit after the given expressions; implies `--no-loop` |
| `--no-loop` | skip the variable loop (`x>`) after an answer |
| `--no-ask` | fail on a missing value instead of asking; `const` replaces without asking |
| `--sym` | start with symbolic algebra on |
| `--no-color`, `--no-colors` | colors off |
| `--color` | colors on, overriding `NO_COLOR` and `--pipe` |
| `--prec N` | display N digits |
| `--set A=1` | store a variable first (`--set "a=1 b=2"` for several) |
| `--const A=1` | store a constant first |
| `--load NAME` | load a save instead of the default one |
| `--no-default` | do not load the default save |
| `--saves FILE` | save file, like `DCALC_SAVES` |
| `--version` | version, and the Python, mpmath and gmpy2 in use |
| `--help` | option list |

Colors are off for `--pipe`, and for `--no-prompt` when the output is not a terminal.
The last of `--color` and `--no-color` wins. `NO_COLOR=1` also turns colors off.

`--prec`, `--set`, `--const` and `--load` run silently before the first expression.
If one fails, nothing else runs.

```
$ python dcalc.py --no-prompt "sin(pi/6)" "2^64"
0.5
18446744073709551616
$ echo "1/3" | python dcalc.py --pipe --prec 10
0.3333333333
$ cat prices.txt
# price with 21% tax
x*1.21
$ python dcalc.py --pipe --set x=100 < prices.txt
121
$ python dcalc.py --no-prompt --set "a=2 b=3" --const k=10 "a*b+k"
16
```

With `--pipe`, a failing line does not stop the others. Its message goes to stderr:

```
$ printf '2+2\n1/0\nsqrt(16)\n' | python dcalc.py --pipe 2>/dev/null
4
4
```

Exit status: 0 on success (an interactive session always ends with 0), 1 if an
expression or command failed (`--pipe`, `--no-prompt`), 2 for invalid usage or a failed
start-up option.

## Errors

An error is printed in red, with the expression the program saw in brackets below:

```
1/0       → Division by zero.
sqrt(     → Unclosed '('.
1.2.3     → Invalid number '1.2.3'.
```
