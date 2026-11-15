------------------------------- MODULE Player -------------------------------
(***************************************************************************)
(* A model of the part of the html-slides player (the ENGINE JS block in   *)
(* skills/html-slides/assets/template.html) that decides how playback      *)
(* advances.                                                               *)
(*                                                                         *)
(*   Modelled: play / pause / go / restartPart / step / finish / wait /    *)
(*             speak (device voice, embedded audio, captions only) and     *)
(*             the slide overview.                                         *)
(*   Left out: appearance (scaling, caption position) and durations.       *)
(*             A timer is only known to fire eventually; timers may fire   *)
(*             in any order.                                               *)
(*                                                                         *)
(* The speech engine is not trusted: its start, end and error              *)
(* notifications may or may not arrive, and a notification about an        *)
(* utterance we cancelled may arrive later.                                *)
(*                                                                         *)
(* Run it with tests/tla/run.sh                                            *)
(***************************************************************************)
EXTENDS Integers, Sequences, FiniteSets

CONSTANTS Parts,       \* Parts[s][c] = number of sentences in cue c (one data-say) of slide s
          MaxUser,     \* bound on the number of user actions (keeps the state space finite)
          HasClips,    \* is there embedded audio (add_voice.py)?
          LocalVoice,  \* is there an on-device voice?
          Fixed        \* TRUE: the code after the fix / FALSE: the code before it

\* The deck used for checking: slide 1 has a two-sentence cue and a one-sentence cue; slide 2 has a one-sentence cue
SmallDeck == <<<<2, 1>>, <<1>>>>

N == Len(Parts)
NCues(s) == Len(Parts[s])
NParts(s, c) == Parts[s][c + 1]
AllCues(s) == 0 .. (NCues(s) - 1)

VARIABLES
  cur, cue, part,   \* current slide and narration position (cueIdx, partIdx)
  hidden,           \* cues of the current slide that are still hidden (.pending)
  playing, mid, ended, tok, startVis,
  ovOpen, ovResume, \* slide overview
  muted, voices, bootOver, ttsBroken, ttsFails, audioBroken,
  timers,           \* callbacks scheduled with wait(): [k, my]
  inv,              \* the most recent speak() call (the contents of its closure)
  eng,              \* the speech engine's state for that utterance
  au,               \* state of the shared Audio element
  budget, lastUser, err

vars == <<cur, cue, part, hidden, playing, mid, ended, tok, startVis, ovOpen, ovResume,
          muted, voices, bootOver, ttsBroken, ttsFails, audioBroken, timers, inv, eng, au,
          budget, lastUser, err>>

slideVars == <<cur, cue, part, hidden>>
ttsVars   == <<ttsBroken, ttsFails, audioBroken>>
envVars   == <<voices, bootOver>>
ovVars    == <<ovOpen, ovResume>>
view      == <<cur, cue, part, hidden, ended, playing>>

NoInv == [my |-> 0, pos |-> <<0, 0, 0>>, fired |-> TRUE, began |-> FALSE, failed |-> FALSE,
          mode |-> "none", ev |-> {}]

Cancel(e) == IF e \in {"queued", "speaking"} THEN "cancelled" ELSE e

\* which path speak() takes (m: muted, ab: audioBroken, tb: ttsBroken)
SpeakMode(m, ab, tb) ==
  IF m THEN "silent"
  ELSE IF HasClips /\ ~ab THEN "audio"
  ELSE IF voices = "none" /\ ~tb /\ ~bootOver THEN "waitvoice"
  ELSE IF tb \/ voices # "local" THEN "silent"
  ELSE "tts"

NewInv(my, p, mode) ==
  [my |-> my, pos |-> p, fired |-> FALSE, began |-> FALSE, failed |-> FALSE, mode |-> mode,
   ev |-> CASE mode = "silent"    -> {"silent"}
            [] mode = "audio"     -> {"wd"}
            [] mode = "waitvoice" -> {"retry"}
            [] OTHER              -> {"wd", "st", "poll"}]

Init ==
  /\ cur = 1 /\ cue = 0 /\ part = 0 /\ hidden = {}
  /\ playing = FALSE /\ mid = FALSE /\ ended = FALSE /\ tok = 1 /\ startVis = TRUE
  /\ ovOpen = FALSE /\ ovResume = FALSE
  /\ muted = FALSE /\ voices \in {"none", IF LocalVoice THEN "local" ELSE "nolocal"}
  /\ bootOver = FALSE /\ ttsBroken = FALSE /\ ttsFails = 0 /\ audioBroken = FALSE
  /\ timers = {} /\ inv = NoInv /\ eng = "idle" /\ au = "idle"
  /\ budget = MaxUser /\ lastUser = FALSE /\ err = ""

-----------------------------------------------------------------------------
(* User actions *)

\* pause()
PauseEff ==
  /\ playing' = FALSE /\ tok' = tok + 1 /\ timers' = {}
  /\ eng' = Cancel(eng) /\ au' = "idle"
  /\ UNCHANGED <<slideVars, mid, ended, startVis, inv>>

\* play(): the arguments are the state just before the call, because it is sometimes called right after go() (as from the overview)
PlayFrom(e, m, c, q, r, h, t) ==
  LET reset == e \/ ~m
      c1 == IF e THEN 1 ELSE c
  IN /\ cur' = c1
     /\ cue' = IF reset THEN 0 ELSE q
     /\ part' = IF reset THEN 0 ELSE r
     /\ hidden' = IF reset THEN AllCues(c1) ELSE h
     /\ ended' = FALSE /\ playing' = TRUE /\ startVis' = FALSE /\ mid' = TRUE
     /\ tok' = t + 1 /\ timers' = {[k |-> "step", my |-> t + 1]}
     /\ eng' = Cancel(eng) /\ au' = "idle"
     /\ UNCHANGED inv

User(A) == /\ budget > 0 /\ budget' = budget - 1 /\ lastUser' = TRUE /\ A

\* Space, a click, or the play button on the start screen
Toggle ==
  User(/\ ~ovOpen
       /\ IF playing THEN PauseEff ELSE PlayFrom(ended, mid, cur, cue, part, hidden, tok)
       /\ UNCHANGED <<ovVars, muted, envVars, ttsVars, err>>)

\* go(i): arrow keys, the progress bar, a swipe, or a change of the URL hash
Go(i) ==
  User(/\ i \in 1 .. N
       /\ cur' = i /\ cue' = 0 /\ part' = 0 /\ ended' = FALSE
       /\ eng' = Cancel(eng) /\ au' = "idle"
       /\ IF playing
            THEN /\ hidden' = AllCues(i) /\ mid' = TRUE /\ tok' = tok + 2
                 /\ timers' = {[k |-> "step", my |-> tok + 2]}
                 /\ UNCHANGED startVis
            ELSE /\ hidden' = {} /\ mid' = FALSE /\ tok' = tok + 1 /\ timers' = {}
                 /\ startVis' = FALSE
       /\ UNCHANGED <<playing, inv, ovVars, muted, envVars, ttsVars, err>>)

\* restartPart(): a change of speed or voice
Restart ==
  User(/\ ~ovOpen /\ playing
       /\ tok' = tok + 1 /\ timers' = {[k |-> "step", my |-> tok + 1]}
       /\ eng' = Cancel(eng) /\ au' = "idle"
       /\ UNCHANGED <<slideVars, playing, mid, ended, startVis, inv, ovVars, muted, envVars, ttsVars, err>>)

\* setMuted(): sound on / off. Turning sound back on also clears the captions-only fallback
MuteToggle ==
  User(/\ ~ovOpen
       /\ muted' = ~muted
       /\ IF muted THEN /\ ttsBroken' = FALSE /\ audioBroken' = FALSE /\ ttsFails' = 0
                   ELSE UNCHANGED ttsVars
       /\ IF playing
            THEN /\ tok' = tok + 1 /\ timers' = {[k |-> "step", my |-> tok + 1]}
                 /\ eng' = Cancel(eng) /\ au' = "idle"
            ELSE UNCHANGED <<tok, timers, eng, au>>
       /\ UNCHANGED <<slideVars, playing, mid, ended, startVis, inv, ovVars, envVars, err>>)

OpenOv ==
  User(/\ ~ovOpen /\ ovOpen' = TRUE /\ ovResume' = playing
       /\ IF playing THEN PauseEff
          ELSE UNCHANGED <<slideVars, playing, mid, ended, tok, startVis, timers, inv, eng, au>>
       /\ UNCHANGED <<muted, envVars, ttsVars, err>>)

CloseOv ==
  User(/\ ovOpen /\ ovOpen' = FALSE /\ ovResume' = FALSE
       /\ IF ovResume THEN PlayFrom(ended, mid, cur, cue, part, hidden, tok)
          ELSE UNCHANGED <<slideVars, playing, mid, ended, tok, startVis, timers, inv, eng, au>>
       /\ UNCHANGED <<muted, envVars, ttsVars, err>>)

\* clicking a thumbnail in the overview: closeOverview(true); go(i); if (r) play();
Thumb(i) ==
  User(/\ ovOpen /\ i \in 1 .. N /\ ovOpen' = FALSE /\ ovResume' = FALSE
       /\ IF ovResume
            THEN PlayFrom(FALSE, FALSE, i, 0, 0, {}, tok + 1)
            ELSE /\ cur' = i /\ cue' = 0 /\ part' = 0 /\ hidden' = {} /\ mid' = FALSE
                 /\ ended' = FALSE /\ startVis' = FALSE /\ tok' = tok + 1 /\ timers' = {}
                 /\ eng' = Cancel(eng) /\ au' = "idle"
                 /\ UNCHANGED <<playing, inv>>
       /\ UNCHANGED <<muted, envVars, ttsVars, err>>)

\* the viewer switched to another tab (visibilitychange)
HidePage ==
  User(/\ playing /\ PauseEff
       /\ UNCHANGED <<ovVars, muted, envVars, ttsVars, err>>)

-----------------------------------------------------------------------------
(* The passage of time, and notifications from outside *)

Async(A) == /\ lastUser' = FALSE /\ UNCHANGED budget /\ A

\* done(): one sentence has finished
DoneEff ==
  LET last == part + 1 >= NParts(cur, cue)
  IN /\ part' = IF last THEN 0 ELSE part + 1
     /\ cue' = IF last THEN cue + 1 ELSE cue
     /\ timers' = timers \cup {[k |-> "step", my |-> inv.my]}
     /\ UNCHANGED <<cur, hidden>>

\* fin(): src says what triggered it; rm is the set of watchers that stop at the same time
FinEff(src, rm, note) ==
  IF inv.fired
    THEN /\ inv' = [inv EXCEPT !.ev = @ \ rm]
         /\ err' = IF note # "" THEN note ELSE err
         /\ UNCHANGED <<slideVars, timers>>
    ELSE /\ inv' = [inv EXCEPT !.fired = TRUE, !.ev = (@ \ {"wd", "st", "silent"}) \ rm]
         /\ IF inv.my = tok /\ playing
              THEN /\ DoneEff
                   /\ err' = IF note # "" THEN note
                             ELSE IF inv.pos # <<cur, cue, part>> THEN "advanced because a different sentence finished"
                             ELSE IF inv.failed /\ src # "silent"
                               THEN "a sentence whose narration failed ended without waiting for its caption time (" \o src \o ")"
                             ELSE err
              ELSE /\ err' = IF note # "" THEN note ELSE err
                   /\ UNCHANGED <<slideVars, timers>>

\* fail(): narration did not start, or the engine reported an error. e is the engine state just before
FailEff(e) ==
  IF inv.fired \/ inv.my # tok \/ (Fixed /\ inv.failed)
    THEN /\ eng' = e /\ UNCHANGED <<inv, ttsBroken, ttsFails, err>>
    ELSE /\ eng' = Cancel(e)
         /\ ttsFails' = ttsFails + 1
         /\ ttsBroken' = (ttsBroken \/ ttsFails + 1 >= 2)
         /\ inv' = [inv EXCEPT !.failed = TRUE,
                               !.ev = ((@ \ {"wd", "st"}) \cup {"silent"}) \ (IF Fixed THEN {"poll"} ELSE {})]
         /\ err' = IF inv.failed THEN "one failed sentence was counted twice" ELSE err

\* calling speak(): start narrating the sentence at position p under token my
SpeakEff(my, p, mode) ==
  /\ inv' = NewInv(my, p, mode)
  /\ eng' = IF mode = "tts" THEN "queued" ELSE eng
  /\ au' = IF mode = "audio" THEN "playing" ELSE au

\* a wait(..., step) timer fires
FireStep ==
  \E t \in timers :
    /\ t.k = "step"
    /\ Async(
         IF t.my = tok /\ playing
           THEN /\ tok' = tok + 1
                /\ IF cue >= NCues(cur)
                     THEN /\ timers' = {[k |-> "eos", my |-> tok + 1]}
                          /\ UNCHANGED <<slideVars, mid, inv, eng, au>>
                     ELSE /\ timers' = {}
                          /\ mid' = TRUE /\ hidden' = hidden \ {cue}
                          /\ SpeakEff(tok + 1, <<cur, cue, part>>, SpeakMode(muted, audioBroken, ttsBroken))
                          /\ UNCHANGED <<cur, cue, part>>
           ELSE /\ timers' = timers \ {t}
                /\ UNCHANGED <<slideVars, mid, tok, inv, eng, au>>)
    /\ UNCHANGED <<playing, ended, startVis, ovVars, muted, envVars, ttsVars, err>>

\* after the last sentence of a slide: go to the next slide, or finish()
FireEos ==
  \E t \in timers :
    /\ t.k = "eos"
    /\ Async(
         IF t.my = tok /\ playing
           THEN IF cur < N
                  THEN /\ cur' = cur + 1 /\ cue' = 0 /\ part' = 0 /\ hidden' = AllCues(cur + 1)
                       /\ mid' = TRUE /\ timers' = {[k |-> "step", my |-> t.my]}
                       /\ UNCHANGED <<playing, ended, tok, startVis>>
                  ELSE /\ playing' = FALSE /\ ended' = TRUE /\ mid' = FALSE /\ tok' = tok + 1
                       /\ startVis' = TRUE /\ timers' = {}
                       /\ UNCHANGED slideVars
           ELSE /\ timers' = timers \ {t}
                /\ UNCHANGED <<slideVars, playing, mid, ended, tok, startVis>>)
    /\ UNCHANGED <<inv, eng, au, ovVars, muted, envVars, ttsVars, err>>

Keep == UNCHANGED <<playing, mid, ended, tok, startVis, ovVars, muted, envVars>>

\* captions only: the timer that lasts as long as the sentence
SilentTimer ==
  /\ "silent" \in inv.ev
  /\ Async(/\ FinEff("silent", {"silent"}, "") /\ UNCHANGED <<eng, au, ttsVars>>)
  /\ Keep

\* the watchdog timer, in case the sentence never ends
WdTimer ==
  /\ "wd" \in inv.ev
  /\ Async(/\ FinEff("wd", {"wd"}, "") /\ UNCHANGED <<eng, au, ttsVars>>)
  /\ Keep

\* the retry timer used while the voice list has not arrived
RetryTimer ==
  /\ "retry" \in inv.ev
  /\ Async(/\ IF ~inv.fired /\ inv.my = tok /\ playing
                THEN SpeakEff(inv.my, inv.pos, SpeakMode(muted, audioBroken, ttsBroken))
                ELSE /\ inv' = [inv EXCEPT !.ev = @ \ {"retry"}] /\ UNCHANGED <<eng, au>>
           /\ UNCHANGED <<slideVars, timers, ttsVars, err>>)
  /\ Keep

\* speech engine: started speaking (onstart)
EngStart ==
  /\ inv.mode = "tts" /\ eng = "queued"
  /\ Async(/\ eng' = "speaking"
           /\ inv' = [inv EXCEPT !.began = TRUE, !.ev = @ \ {"st"}]
           /\ UNCHANGED <<slideVars, timers, au, ttsVars, err>>)
  /\ Keep

\* speech engine: finished (onend). It can also arrive for an utterance we cancelled
EngEnd ==
  /\ inv.mode = "tts" /\ eng \in {"queued", "speaking", "cancelled"}
  /\ Async(/\ eng' = "idle"
           /\ IF Fixed /\ (inv.fired \/ inv.failed \/ inv.my # tok)
                THEN UNCHANGED <<inv, slideVars, timers, ttsVars, err>>
                ELSE /\ ttsFails' = 0
                     /\ UNCHANGED <<ttsBroken, audioBroken>>
                     /\ FinEff("onend", {"poll"},
                               IF ttsFails > 0 /\ (eng = "cancelled" \/ inv.failed \/ inv.my # tok)
                                 THEN "the end notification of a cancelled utterance reset the failure count to 0" ELSE "")
           /\ UNCHANGED au)
  /\ Keep

\* speech engine: "interrupted" after a cancel (ignored)
EngErrInterrupted ==
  /\ inv.mode = "tts" /\ eng = "cancelled"
  /\ Async(/\ eng' = "idle" /\ UNCHANGED <<inv, slideVars, timers, au, ttsVars, err>>)
  /\ Keep

\* speech engine: an error (onerror)
EngErrOther ==
  /\ inv.mode = "tts" /\ eng \in {"queued", "speaking", "cancelled"}
  /\ Async(/\ FailEff("idle") /\ UNCHANGED <<slideVars, timers, au, audioBroken>>)
  /\ Keep

\* speech engine: finished without firing onend
EngQuietFinish ==
  /\ inv.mode = "tts" /\ eng = "speaking"
  /\ Async(/\ eng' = "idle" /\ UNCHANGED <<inv, slideVars, timers, au, ttsVars, err>>)
  /\ Keep

\* the check made when onstart has not arrived after 5 seconds
StTimer ==
  /\ "st" \in inv.ev
  /\ \E speaking \in (IF eng = "speaking" THEN {TRUE} ELSE IF eng = "queued" THEN {TRUE, FALSE} ELSE {FALSE}) :
       Async(/\ IF inv.began
                  THEN /\ inv' = [inv EXCEPT !.ev = @ \ {"st"}] /\ UNCHANGED <<eng, ttsVars, err>>
                  ELSE IF speaking
                    THEN /\ inv' = [inv EXCEPT !.began = TRUE, !.ev = @ \ {"st"}]
                         /\ UNCHANGED <<eng, ttsVars, err>>
                    ELSE /\ FailEff(eng) /\ UNCHANGED audioBroken
             /\ UNCHANGED <<slideVars, timers, au>>)
  /\ Keep

\* the poll for engines that never fire onend: if speech has stopped, treat the sentence as finished
PollTick ==
  /\ "poll" \in inv.ev
  /\ \/ /\ (inv.fired \/ inv.my # tok)
        /\ Async(/\ inv' = [inv EXCEPT !.ev = @ \ {"poll"}]
                 /\ UNCHANGED <<slideVars, timers, eng, au, ttsVars, err>>)
     \/ /\ ~inv.fired /\ inv.my = tok /\ inv.began /\ eng \notin {"queued", "speaking"}
        /\ Async(/\ ttsFails' = 0 /\ UNCHANGED <<ttsBroken, audioBroken>>
                 /\ FinEff("poll", {"poll"}, "")
                 /\ UNCHANGED <<eng, au>>)
  /\ Keep

\* embedded audio: played to the end
AudioEnded ==
  /\ inv.mode = "audio" /\ au = "playing"
  /\ Async(/\ au' = "idle" /\ FinEff("audio", {}, "") /\ UNCHANGED <<eng, ttsVars>>)
  /\ Keep

\* embedded audio: playback failed, so that sentence is retried with the device voice or captions only
AudioErr ==
  /\ inv.mode = "audio" /\ au \in {"playing", "rejected"}
  /\ Async(/\ IF inv.fired \/ inv.my # tok
                THEN /\ au' = "idle" /\ UNCHANGED <<inv, eng, audioBroken>>
                ELSE /\ audioBroken' = TRUE
                     /\ inv' = NewInv(inv.my, inv.pos, SpeakMode(muted, TRUE, ttsBroken))
                     /\ eng' = IF SpeakMode(muted, TRUE, ttsBroken) = "tts" THEN "queued" ELSE eng
                     /\ au' = "idle"
           /\ UNCHANGED <<slideVars, timers, ttsBroken, ttsFails, err>>)
  /\ Keep

\* embedded audio: the browser refused to autoplay, so that sentence continues with captions only
AudioRejected ==
  /\ inv.mode = "audio" /\ au = "playing"
  /\ Async(/\ au' = "rejected"
           /\ inv' = IF ~inv.fired /\ inv.my = tok
                       THEN [inv EXCEPT !.ev = (@ \ {"wd", "st"}) \cup {"silent"}] ELSE inv
           /\ UNCHANGED <<slideVars, timers, eng, ttsVars, err>>)
  /\ Keep

\* the voice list arrived / the start-up grace period ended
VoicesArrive ==
  /\ voices = "none"
  /\ Async(/\ voices' = (IF LocalVoice THEN "local" ELSE "nolocal")
           /\ UNCHANGED <<slideVars, playing, mid, ended, tok, startVis, ovVars, muted, bootOver,
                          ttsVars, timers, inv, eng, au, err>>)
BootExpire ==
  /\ ~bootOver
  /\ Async(/\ bootOver' = TRUE
           /\ UNCHANGED <<slideVars, playing, mid, ended, tok, startVis, ovVars, muted, voices,
                          ttsVars, timers, inv, eng, au, err>>)

Next ==
  \/ Toggle \/ (\E i \in 1 .. N : Go(i)) \/ Restart \/ MuteToggle
  \/ OpenOv \/ CloseOv \/ (\E i \in 1 .. N : Thumb(i)) \/ HidePage
  \/ FireStep \/ FireEos \/ SilentTimer \/ WdTimer \/ RetryTimer
  \/ EngStart \/ EngEnd \/ EngErrInterrupted \/ EngErrOther \/ EngQuietFinish \/ StTimer \/ PollTick
  \/ AudioEnded \/ AudioErr \/ AudioRejected \/ VoicesArrive \/ BootExpire

\* a timer that is scheduled always fires eventually
Fairness ==
  /\ WF_vars(FireStep) /\ WF_vars(FireEos) /\ WF_vars(SilentTimer) /\ WF_vars(WdTimer)
  /\ WF_vars(RetryTimer) /\ WF_vars(BootExpire)

Spec == Init /\ [][Next]_vars /\ Fairness

-----------------------------------------------------------------------------
(* Properties to check *)

LiveTimers == {t \in timers : t.my = tok}
LiveInv == inv.my = tok /\ ~inv.fired

\* the pieces of UI state never contradict each other
Consistent ==
  /\ (playing => ~startVis /\ ~ended /\ ~ovOpen /\ mid)
  /\ (ended => ~playing /\ startVis /\ cur = N /\ hidden = {})
  /\ (~mid => hidden = {})                        \* when not mid-slide, every element is revealed
  /\ cue \in 0 .. NCues(cur)
  /\ (cue < NCues(cur) => part \in 0 .. (NParts(cur, cue) - 1))
  /\ (mid => \A c \in AllCues(cur) : (c < cue => c \notin hidden) /\ (c > cue => c \in hidden))

\* while playing there is exactly one thing that can advance playback (0 would mean stuck, 2 or more would mean advancing twice)
OneContinuation ==
  playing => Cardinality(LiveTimers) + (IF LiveInv THEN 1 ELSE 0) = 1

\* the sentence being narrated can always move on by a timer, even if no notification ever arrives
NeverStuck ==
  LiveInv /\ playing => inv.ev \cap {"wd", "silent", "retry"} # {}

\* the sentence being narrated is the one the screen points at, and its element is revealed
SpeakingTheRightSentence ==
  LiveInv /\ playing => inv.pos = <<cur, cue, part>> /\ cue \notin hidden

NoError == err = ""

\* while stopped, nothing on screen changes, whatever time passes or notifications arrive
PausedIsStable == [][(~lastUser' /\ ~playing) => view' = view]_vars

\* once the user stops acting, playback eventually stops (it reaches the end, or stays paused)
EventuallyStops == <>[](~playing)

=============================================================================
