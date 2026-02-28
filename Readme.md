This project unfortunately only works locally, as the Beeper API Desktop (https://developers.beeper.com/desktop-api), only runs locally. 

The website allows me to add people who I want to stay in touch with then parses Beepers API, to see if there are contacts with similar names, it also
allows me to manually search for their contact name (this allows me to connect people on instagram with different usernames than their real name), to
the same contact. I am also able to sync group chats with a contact so if I only talk to people via a gc I can see that as well. Once synced up,
The website calls the Beeper API, using the individual's chat ID, which was selected during the setup stage, and checks when the last time I
sent them a text. It then buckets chats into this week and overdue, (overdue being haven't texted them in ~2 weeks). 

The only secrets are the Beeper Access Token, for which I had to run a script to decrypt that from Beeper, and my settings.json, which saves
The chat IDs associated with the people I want to stay in touch with. The access token is hidden in a .env and the settings.json is in the
.gitignore.

Hypotethically if you wanted to run it locally, you would need to download Beeper on your computer, connect your chats with it, then go to developer mode,
start the API, then run a script to decrypt your Beeper Access Token (I used Claude to help me with that). Then you could add your own people
and connect them with their respective chats pretty intuitively.

The feature I'm most proud of is that while looking through Beepers API, I noticed it saved the Image URL for the profile pictures, and I realized
That meant in my website, I could also add each contact's PFP, which would make looking through it faster, as I immediately recognize most people's PFP.
Another feature I'm proud of is enabling it to check when I last texted someone, so it accounts for the fact that my grandma might have sent me a video,
but I never responded and would still remind me that it's been too long since I last texted her.

