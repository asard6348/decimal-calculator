# Calculator

A calculator you run in the terminal. It works in decimal with 50 digits of
precision and shows 30, so `0.1+0.2` is `0.3` and `1/3` goes on for a while.
It also does complex numbers (with as many imaginary units as you like),
derivatives, integrals, sets, and it can save your session.

It is a single file: `calculator.py`.

## Install

You need Python 3.9 or newer and mpmath:

```
pip install mpmath
```

`pip install gmpy2` is optional. It makes heavy calculations faster.

## Start it

```
python calculator.py
```

You get a `>>` prompt and nothing else. Type `help` to see a short syntax
reference, the other features, and the full list of functions. Press Ctrl+D to quit.

You can also give expressions on the command line. They are evaluated first,
then you get the prompt:

```
python calculator.py "2(5)" "sqrt(2)"
```

To use it in scripts, or to see all the options, read [Command line](#command-line)
(`python calculator.py --help` shows the same list).

## The basics

Type an expression and press Enter.

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

`^` and `**` both mean power. `//` and `%` round down, like in Python, so
`-7//2` is `-4` and `-7%3` is `2`. Division by zero is an error.

Multiplication signs can be left out:

```
2(5)                              → 10
(10/3)3                           → 10
2pi                               → 6.28318530717958647692528676656
x=3;2x**2+1                       → 19
```

A power binds tighter than the hidden multiplication, so `2x**2` is `2*(x**2)`.
A hidden multiplication binds tighter than a division, so `1/2x` is `1/(2x)`.
Use brackets if you want something else.

Complex numbers work out of the box. `i` is the imaginary unit. (You can switch
on more units, see [Imaginary units](#imaginary-units).)

```
sqrt(-4)                          → 2i
(1+2i)*(3-i)                      → 5+5i
abs(3+4i)                         → 5
```

You can paste text from other places. These characters are understood:
`−` `×` `÷` `π` `²` `³`.

```
5−3                               → 2
2×3                               → 6
```

There is no `5!`. Use `fact(5)`.

## Variables

A variable is a single letter, or a word between underscores like `_speed_`.

Set one inline, then write the expression after a semicolon:

```
x=3;x^2                           → 9
_speed_=5;_speed_*2               → 10
```

If an expression uses a variable you have not set, the calculator asks for it.
After the answer it stays in a small loop where you can change the values and
see the result again:

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

In the loop you can:

- type a number or expression to change the variable shown in the prompt
- type `x=...` to change another variable
- press Enter on an empty line to see the result again
- type `new` or `back` to leave

A value you type at the prompt wins over an inline assignment. While you are
being asked for the variables, `back` goes to the previous question and `new`
drops the expression.

What is remembered: functions and sets you assign stay for the whole session, and
so do the variables and constants you store with `var` and `const`. Plain numbers
do not, you are asked again on the next line. Use `var` for a number you want to
keep and change, `const` for one that should not change by accident.

Assignment operators work too: `+=` `-=` `*=` `/=` `//=` `**=` `|=`.

```
x=10;x//=3;x                      → 3
f="x";f+=1;f(5)                   → 6
```

## Functions

`help` lists every function. The ones you will probably use:

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

Trigonometry and its inverses (`sin`, `asin`, `sinh`, ...), `abs`, `floor`,
`ceil`, `round`, `sign`, `gamma`, `erf`, `zeta`, Bessel functions and a lot
more come from mpmath.

Statistics take numbers or a set:

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

Others: `size(3,4)` is the length of the vector, `len(12.34)` counts the
digits of a number, the letters of a string, the items of a set.

```
size(3,4)                         → 5
len(12.34)                        → 4
```

## Stored variables

`var` keeps a variable for the whole session, whatever it holds: a number, a
function, a set. A stored variable is never asked for again.

```
var k 1/3            store it
var k=1/3            the same
var a=1 b=2          store several, see below
var k                show it
var k+=1             change it (also *=, -=, ...)
var                  list them all
varrm a b            remove one or more
varrmall             remove all variables (constants stay)
```

To store several at once, write them as `name=value` one after the other. A
value may contain spaces, the next `name=` starts the next variable, and a
later one can use an earlier one. The same goes for `const`.

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

Changing a variable asks nothing. If the name belongs to a constant, `var`
refuses and tells you to use `const`. `var(1,2,3)` is still the variance function.

Functions and sets you assign (`f="x**2"`, `s={1,2}`) are stored as variables
too, so `var` lists them and `varrm` and `varrmall` forget them.

## Constants

Built in: `pi`, `e`, `tau`, `phi`, `euler`, `catalan`, `sqrt2`, `sqrt3`,
`ln2`, `ln10`, `inf`, `ninf`, `nan`, `true`, `false`, and some physics ones:
`light`, `planck`, `boltzmann`, `avogadro`, `echarge`, `grav`, `gravity`,
`hbar`.

```
tau                               → 6.28318530717958647692528676656
light                             → 299792458
```

Your own constants are kept for the session, are not removed by `varrmall`, and
can be saved:

```
const k 1/3          define
const l=2 p=3        define several
const k              show it
const k+=1           change it (also *=, -=, ...)
const                list them all
constrm k l          remove one or more
constex k            does it exist? (True/False)
constin k            type and value
constrmall           remove all
```

If the name is already taken, `const` asks before replacing it. `constrm`,
`constex` and `constin` take several names too; `constex` then prints one
`name: True` or `name: False` per name.

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

These commands only know about constants. A function or set you made with
`f="x**2"` or `s={1,2}` is not a constant, it is a variable: `varrm` forgets it.

## Your own functions

A function is a quoted expression. The free variables are its parameters.

```
f="x**2+3x";f(2)                  → 10
f="x+y";run(f,2,3)                → 5
```

You can do arithmetic with them: `f+g`, `f*2`, `f+=1`.

### Derivatives

`diff` gives a new function. It knows the usual functions and tells you when it
does not know one.

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

`integrate` stops with an error if the integral does not seem to converge.
`limit` and `nsum` use extrapolation. They are accurate for ordinary cases but
not for very slow ones, like `ln(x)/x` at infinity. A divergent sum such as
`1/x` is not detected.

## Sets

```
{1,2,3}                           → {1,2,3}
{1,2,3}[1]                        → 2
{1,2,3}[4]                        → 2
```

Counting starts at 0 and an index past the end wraps around.

On a finite set, `+` adds a member, `-` removes one, and `*`, `/`, `//`, `**`
work on every member. `|` is union.

```
{0}+1                             → {0,1}
{1,2,3}-2                         → {1,3}
{1,2}*3                           → {3,6}
{1,2}|{2,3}                       → {1,2,3}
sort({3,1,2})                     → {1,2,3}
```

A set can also be a range: `{>=0<10}`, or two ranges: `{<0,>5}`. `+` and `*`
move or stretch the range.

```
{>0}+1                            → {>1}
{>=0<10}[5]                       → 5
~range(0,3)                       → {0,1,2}
~2.5                              → 2
```

`~` rounds. On a number it gives a whole number, on a set it gives the whole
numbers inside it. Halves go to the even number, the same as `round`.

You can give single indexes their own value, or a rule for all indexes:

```
x={0};x[3]=7;x                    → {0,[3]=7}
x={0};x[3]=7;x[3]                 → 7
x={[*2]=>=0};x[4]                 → 8
x={[+1]=>7};x[8]                  → 2
```

`{[*2]=>=0}` means index `i` gives `i*2`. In `{[+1]=>7}` the index wraps at 7
first, so `i` gives `(i mod 7)+1`. With `>=0` the index is used as it is.

You can compare sets. `<=` and `<` mean subset.

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
`~=` rounds both sides to whole numbers first. `!` means not, and it is true
for 0, an empty set and an empty string.

`(A):IF(c):(B)` gives `A` when the condition is true and `B` when it is not.
You can give several conditions separated by commas, all of them must be true.

## Repeating

`repeat` runs steps a number of times. `until` runs them until a condition
is true. A step is `x=...`, `x*=...`, or `x+=` alone, which adds 1 to a number
or the next item to a set of numbers.

```
x=1;repeat(x*=2,10)               → 1024
x=0;until(x+=,x>9)                → 10
x={0,1};until(x+=,x[10]==10)      → {0,1,2,3,4,5,6,7,8,9,10}
```

`until` gives up after 100000 rounds.

## Text

Text goes between square brackets. In front of an expression it is printed
before the result:

```
[total: ]2+2                      → total: 4
```

A text in square brackets can also be an index: `p[[work]]=5;p[[work]]`.

## Imaginary units

`i` is the imaginary unit, and you start with just that one. You can have more
units, so that a number gets several independent imaginary parts. A unit is named
by one letter or a word between underscores.

```
img                  list the units
img j k              add units; a unit you already have is switched on or off
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

Every unit squares to -1, and different units do not mix: `i*j` is a part of its
own, written `ij`, and it squares to +1.

```
>> i*j
ij
>> (i*j)^2
1
>> (i+j)*(i-j)
0
```

Brackets are multiplied out for you, and `+ - * /` and whole-number powers work
with any mix of units. Functions (`sqrt`, `exp`, `sin`, `abs`, `re`, `im`,
non-whole powers...) take numbers with one unit at a time, because they are
defined for ordinary complex numbers. `a+b*u` with any single unit `u` is
treated as the complex number `a+b*i`, so for example:

```
>> sqrt(3+4j)
2+j
>> abs(3+4j)
5
>> exp(j*pi)
-1
```

Mixing two units inside one function, like `sin(i+j)`, is an error. Dividing by a
number that has no inverse (like `1+i*j`) is an error too.

### On, off and removed

Giving a name you already have to `img` switches that unit off, or on again. An
unit that is off stays in the list, but its name is a normal name again. `imgrm`
takes a unit out of the list completely.

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

The first unit in the list that is on is the **main** unit. A real negative root
gives the main unit, so `sqrt(-4)` is `2i` now. Switch `i` off and `j` takes over.
Numbers you have stored keep their meaning when that happens.

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

With no unit left on, `sqrt(-4)` is an error. A unit cannot share its name with
a variable, a constant, or a built-in name (`e`, `pi`...): remove the variable
first, or pick another name.

The units, their order and their on/off state are saved and loaded with `save`
and `load`.

## Commands

| Command | What it does |
| --- | --- |
| `help` | syntax reference, features and all functions |
| `new` | leave the current question or loop |
| `back` | go back one question |
| `img ...` | your imaginary units: `img`, `imgrm`, `imgrmall`, see above |
| `prec 50` | show 50 digits (the calculator uses 20 more inside), `prec` alone shows the setting |
| `var ...` | your variables: `var`, `varrm`, `varrmall`, see above |
| `const ...` | your own constants: `const`, `constrm`, `constex`..., see above |
| `save`, `load` and friends | see below |

## Saving

```
save work            save variables, functions, sets, constants and the imaginary units
load work
saves                list them, a * marks the default one
saverm work          delete one
savesrmall           delete all
saveren work newname   rename
savedefault work     load this one every time the program starts
savedefault          save the current state as "default" and use it at start
```

The saves are written to `calculator_saves.json` in the folder you start
the program from. The file is created the first time you save. Set the
environment variable `CALC_SAVES` to use another path.

## Command line

```
python calculator.py [options] [--] [expression ...]
```

An argument is an option only if it is in the lists below, so an expression such
as `-7//2` can be given as it is. If you want to be sure, put `--` before the
expressions.

### Modes

| Option | What it does |
| --- | --- |
| `--pipe` | Script mode. Also reads expressions from standard input, one per line, and prints only the results: no prompt, no colors, no questions. Errors go to standard error. Empty lines and lines starting with `#` are skipped. |
| `--no-prompt` | Evaluates the expressions on the command line, then exits instead of showing the `>>` prompt. There is no variable loop either. |
| `--no-loop` | After an answer, does not stay in the variable loop (the `x>` prompt), see [Variables](#variables). |
| `--no-ask` | Never asks for a missing value: it is an error instead. `const` replaces an existing constant without asking. |

`--pipe` means `--no-ask` and `--no-loop` as well. A value that is needed but
missing is reported with the way to give it one:

```
$ echo "x*2" | python calculator.py --pipe
'x' has no value. Give it one first: x=5;<expression>, var x 5, or --set x=5
```

### Look

| Option | What it does |
| --- | --- |
| `--no-color`, `--no-colors` | Turns the colors off, like `NO_COLOR=1`. |
| `--color` | Forces the colors on, even if `NO_COLOR` is set. |

Without these, colors are on, except for `--pipe`, and for `--no-prompt` when
the output goes to a file or a pipe. The last of `--color` and `--no-color`
wins.

### Start-up

| Option | What it does |
| --- | --- |
| `--prec N` | Shows N digits, like the `prec` command. |
| `--set A=1` | Stores a variable first, like `var`. Write `--set "a=1 b=2"` for several, or repeat the option. |
| `--const A=1` | Stores a constant first, like `const`. |
| `--load NAME` | Loads a save instead of the default one. |
| `--no-default` | Does not load the default save. |
| `--saves FILE` | Keeps the saves in FILE, like `CALC_SAVES`. |
| `--help` | Shows the list of options and exits. |

These steps run before the first expression, silently. If one fails, nothing
else runs and the exit status is 2.

### Examples

```
$ python calculator.py --no-prompt "sin(pi/6)" "2^64"
0.5
18446744073709551616
$ echo "1/3" | python calculator.py --pipe --prec 10
0.3333333333
$ cat prices.txt
# price with 21% tax
x*1.21
$ python calculator.py --pipe --set x=100 < prices.txt
121
$ python calculator.py --no-prompt --set "a=2 b=3" --const k=10 "a*b+k"
16
```

In `--pipe` mode a failing line does not stop the others. Its message goes to
standard error, so the results stay clean:

```
$ printf '2+2\n1/0\nsqrt(16)\n' | python calculator.py --pipe 2>/dev/null
4
4
```

### Exit status

| Status | Meaning |
| --- | --- |
| 0 | Everything worked. An interactive session always ends with 0. |
| 1 | An expression or command failed (only for `--pipe` and `--no-prompt`). |
| 2 | A mistake on the command line, or a start-up step failed. |

## Settings

- `NO_COLOR=1` or `--no-color` turns the colors off.
- `CALC_SAVES=path` or `--saves path` sets where saves are kept.
- `prec` and `img` are described above, `--prec` is the command-line form of `prec`.

## Errors

An error is printed in red with the expression the program saw in brackets
under it:

```
1/0                               → Division by zero.
sqrt(                             → Unclosed '('.
1.2.3                             → Invalid number '1.2.3'.
```

## Tests

```
python test_calculator.py
```

It takes about two minutes. It runs several hundred calculations, checks the
section order of `calculator.py`, and runs every `→` example in this file.
