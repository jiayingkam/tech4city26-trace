// Quiz content for the "Privacy IQ" module surfaced from Settings.
// Each topic is a short, self-contained round: a handful of scenario-based
// questions plus a one-line takeaway shown at the end of the round.
export const traceQuiz = [
  {
    topic: 'Anatomy of a Leak',
    subtitle: 'How one ordinary detail becomes an attack surface',
    takeaway: "The leak is invisible by design — that's why platforms miss it and attackers don't.",
    questions: [
      {
        question: 'A photo taken at home is uploaded straight from the camera roll with no location typed anywhere. What can an attacker still extract from the raw file?',
        options: [
          'Only the phone model',
          'Nothing — location only exists if you type it',
          'GPS coordinates and a timestamp embedded in the EXIF metadata',
          'Your contact list',
        ],
        correctIndex: 2,
        explanation: "The leak isn't in what you wrote — it's baked into the file. Most people never see EXIF data, which is exactly why platforms don't catch it and attackers do.",
      },
      {
        question: 'Your uniform crest is visible in a selfie. On its own it seems harmless. What turns it into a targeting tool?',
        options: [
          'Combined with post timing, it narrows where you are and when to a predictable window',
          "It never can — a school isn't sensitive",
          'Only if the photo is public',
          'Only if you tag the school',
        ],
        correctIndex: 0,
        explanation: "Attackers don't need your address — a location that repeats on a schedule is enough to intercept someone in the physical world.",
      },
      {
        question: 'An attacker takes your ordinary balcony photo and runs it through reverse image search and shadow/skyline analysis. What are they doing?',
        options: [
          'Hacking your phone',
          'Editing your photo',
          "Nothing useful — a photo can't reveal a location",
          'Open-source intelligence (OSINT): geolocating you from background clues you never noticed',
        ],
        correctIndex: 3,
        explanation: "The threat isn't a hacker breaking in. It's a stranger assembling public clues you handed over for free.",
      },
      {
        question: 'You post a photo showing the corner of your student card / an event QR pass. Why is this rated an identifying-document risk?',
        options: [
          'QR codes can install viruses through a screen',
          'It links your anonymous-feeling posts to your real legal identity',
          "It's only risky if scanned in person",
          'Cards are never sensitive',
        ],
        correctIndex: 1,
        explanation: "One document collapses the gap between 'online persona' and 'real person' — the exact bridge stalkers, scammers and doxxers need.",
      },
      {
        question: "What's the macro reason single-photo blur apps and platform moderation can't solve this?",
        options: [
          "They're too expensive",
          "Users don't install them",
          'They only work on video',
          'They react to one object, after publishing, with no memory of everything posted before',
        ],
        correctIndex: 3,
        explanation: "The entire safety ecosystem is reactive and per-post — so the aggregate exposure keeps growing unchecked. That's the gap Trace fills.",
      },
    ],
  },
  {
    topic: 'The Mosaic Effect',
    subtitle: 'Aggregation, and why it scales into a systemic problem',
    takeaway: 'Small leaks compound into a profile no single post reveals.',
    questions: [
      {
        question: "Mia posts a uniform selfie (Mon), a window with a legible block number (Wed), and 'Home alone all week, parents in KL!' (Fri). How many would any platform flag today?",
        options: [
          'All three',
          "Just Friday's",
          'Zero — each is individually rule-compliant',
          'The block number one',
        ],
        correctIndex: 2,
        explanation: 'Every filter judges posts in isolation. The threat lives in the combination, which no current platform is built to see.',
      },
      {
        question: "What is the core mechanism that makes 'mosaic' exposure dangerous?",
        options: [
          'Posting too frequently',
          'Using the wrong privacy settings',
          'Having too many followers',
          'Individually low-risk data points aggregating into a high-confidence profile',
        ],
        correctIndex: 3,
        explanation: 'This is aggregation risk — the same principle behind large-scale de-anonymisation. Small leaks compound.',
      },
      {
        question: "Trace's Mosaic Engine says it can infer your neighbourhood at 'medium confidence' from two unrelated posts months apart. Why cite the confidence level?",
        options: [
          'To look technical',
          'Because attackers also work in probabilities — partial certainty is still actionable',
          "It's legally required",
          'To slow the app down',
        ],
        correctIndex: 1,
        explanation: "A stalker doesn't need 100%. Narrowing you to a few blocks with 'medium confidence' is already a real-world threat.",
      },
      {
        question: 'Why does mosaic exposure make cyber safety a collective problem, not just a personal one?',
        options: [
          'It doesn’t — it only affects the poster',
          'It only matters for public figures',
          'Your posts also leak details about friends, family, and bystanders who never consented',
          "It's a platform's problem alone",
        ],
        correctIndex: 2,
        explanation: "Your feed is a map of other people's routines too. One person's oversharing erodes the whole group's safety — that's the macro effect.",
      },
      {
        question: 'At scale across a whole generation posting daily, what is the compounding societal risk?',
        options: [
          'Oversharing becomes the norm, making everyone easier to target and normalising exposure',
          'Slower internet',
          'Phones run out of storage',
          'Nothing changes at scale',
        ],
        correctIndex: 0,
        explanation: 'When everyone leaks a little, doxxing, scams and stalking get cheaper and easier for everyone — cyber safety degrades system-wide.',
      },
    ],
  },
  {
    topic: 'Downstream Harm',
    subtitle: 'What leaked data actually enables',
    takeaway: 'Leaked data is a weapon others use — the cheapest place to stop it is before it leaves your phone.',
    questions: [
      {
        question: "A 'friendly' stranger DMs you already knowing your school and daily bus. What attack does public data enable here?",
        options: [
          "Nothing — it's a coincidence",
          'A computer virus',
          'A wrong number',
          'Social engineering / grooming: using real facts to fast-track trust',
        ],
        correctIndex: 3,
        explanation: 'Leaked context is the raw material for manipulation. Removing the self-exposure upstream is what starves it — before any report is even possible.',
      },
      {
        question: 'How can scattered public details lead to an account being compromised, not just a person?',
        options: [
          "They can't — passwords are separate",
          'Birthday, school, pet name and location feed answers to security questions and targeted phishing',
          'Only if you post your password',
          'Only through malware',
        ],
        correctIndex: 1,
        explanation: "'Harmless' trivia is exactly what account-recovery and phishing exploit. The leak in one place cascades into another.",
      },
      {
        question: "Singapore criminalises doxxing and can order takedowns. Why isn't that enough on its own?",
        options: [
          "The laws don't work",
          'Nobody enforces them',
          "They're reactive — they act after harm, and can't see mosaic leakage building up",
          'They only cover adults',
        ],
        correctIndex: 2,
        explanation: 'Legal safeguards trigger after publication and after damage. The gap is prevention — catching exposure before it leaves the phone.',
      },
      {
        question: "'Home alone all week, parents in KL!' is announced publicly. Beyond embarrassment, what's the concrete threat?",
        options: [
          "None — it's just a status",
          'Only that friends might visit',
          'It lowers your follower count',
          'It advertises a known, unsupervised, time-boxed window — useful for burglary or physical targeting',
        ],
        correctIndex: 3,
        explanation: 'This converts a social post into operational intelligence for someone planning real-world harm.',
      },
      {
        question: 'Why is a 15-minute cooldown on a high-risk post a genuine safety mechanism, not just a nag?',
        options: [
          'It permanently blocks bad posts',
          "It interrupts the impulse — separating 'post now' from 'do I still want to?' before harm is irreversible",
          'It reports you to your parents',
          'It deletes the photo',
        ],
        correctIndex: 1,
        explanation: 'Most oversharing is impulsive, not malicious. A pause is the cheapest point in the whole chain to stop a leak that can never be recalled.',
      },
    ],
  },
]
