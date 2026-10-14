# Bouncy Energy – arbitrage depth (privat projekt)

Det här är modellen för arbitragedjup, helt skild från den publika sidan. Inget här publiceras.
Resultatet är **en enda HTML-fil** (`viewer/arbitrage.html`) som du laddar ner och öppnar på din egen dator.

## Så sätter du upp det (en gång, ca 30 minuter)

1. **Nytt repo.** På GitHub: **+** uppe till höger → *New repository*. Namn: `bouncy-arbitrage`. Välj **Private** (inte Public). *Create repository*.
2. **Token.** *Settings → Secrets and variables → Actions → New repository secret*. Namn: `ENTSOE_API_KEY`, värde: din ENTSO-E-token.
3. **Ladda upp filerna.** Packa upp zip-filen. På repots förstasida: *uploading an existing file*. Dra in `update_data.py`, `build_viewer.py`, `viewer_template.html`, `requirements.txt` och `README.md`. Klicka *Commit changes*.
4. **Flödesfilen.** *Add file → Create new file*. Skriv namnet `.github/workflows/update.yml` (med snedstreck). Öppna `WORKFLOW-update.yml.txt` i Anteckningar, kopiera allt och klistra in. *Commit changes*. Det startar första körningen.
5. **Vänta.** Följ körningen under **Actions**. Första gången tar den ungefär 40–60 minuter, eftersom all historik hämtas och modellen räknas. Därefter går det mycket snabbare.

## Så tittar du på resultatet

1. När körningen är grön: öppna mappen **viewer** i repot och klicka på `arbitrage.html`.
2. Klicka på ikonen **Download raw file** (pil nedåt, uppe till höger ovanför filinnehållet).
3. Dubbelklicka på den nedladdade filen. Den öppnas i webbläsaren. All data ligger inbäddad i filen, men sidan behöver internet för att ladda diagrambiblioteket.

## Uppdateringar

* Jag skickar nya filer. Ladda upp dem i repot på samma sätt (de som ändrats räcker). Det startar en ny körning automatiskt.
* Annars körs flödet automatiskt varje måndag. Du kan också starta det själv: *Actions → Update data and build viewer → Run workflow*.
* Arbitragedjupet räknas bara om när underlaget ändrats (ny månad eller ändrade antaganden), så vanliga körningar går fort.

## Att veta

* Det privata repot använder dina Actions-minuter. På GitHubs gratisplan finns ett månadstak (kolla under *Settings → Billing*). Eftersom flödet bara körs en gång i veckan ska det räcka gott.
* Repot är privat, så sidan går inte att nå för andra. Den publika sajten (Swedish electricity market) ligger i ett annat repo och påverkas inte.
* Antaganden (verkningsgrad, effekt per MW, urval av dygn) ligger överst i `update_data.py` i sektionen *Arbitragedjup*.
