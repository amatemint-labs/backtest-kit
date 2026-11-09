# Pre-registration: sample-futures-crypto (synthetic data)

idea: heavy volume on the 1h and 15m bars comes before up-moves in futures and crypto too
entry: buy the future or the coin at the 1h close on the first bar of each volume_surge signal
exit: sell when price turns 0.75 day-ATR off its best point since entry, or after 5 trading days
measure: median move in day-ATRs and win rate for signal entries vs all bars, in each half
pass_mark: signal median move at least +0.5 day-ATR and win rate above 55% in both halves

## Settings the kit reads (change only before running)
label: C_2atr
grades: A, B
trail_k: 0.75
exhaustion: yes
signal: volume_surge

## Verdict (append after running; never edit above this line)
