# Pre-registration: sample-study (synthetic data)

idea: heavy volume on the 1h and 15m bars comes before up-moves worth buying calls for
entry: buy the ATM call at the 1h close on the first bar of each volume_surge signal
exit: sell when price turns 0.75 day-ATR off its best point since entry, or at expiry
measure: median option multiple, % doubled, % lost half — signal entries vs all bars, each half
pass_mark: signal median multiple at least 1.2x the all-bars median in BOTH halves

## Settings the kit reads (change only before running)
label: C_1x
grades: A, B
trail_k: 0.75
exhaustion: yes
min_premium: 0.20
signal: volume_surge

## Verdict (append after running; never edit above this line)
