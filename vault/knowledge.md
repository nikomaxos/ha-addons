# Home Assistant Knowledge Vault

Αυτό το αρχείο περιέχει πολύτιμη τεχνική γνώση που έχει αποκομίσει ο AI Assistant (ή ο χρήστης) από την ενασχόληση με το συγκεκριμένο Home Assistant setup. Πρέπει να ελέγχεται σε περίπτωση troubleshooting.

## 1. Σύνδεση με SSH και Python (Paramiko)
- Η απευθείας χρήση των Windows OpenSSH tools (`ssh`, `scp`) προκαλούσε προβλήματα authentication.
- Η βέλτιστη και πιο αξιόπιστη μέθοδος είναι το script `vault/scripts/ssh_run.py`, το οποίο χρησιμοποιεί τη βιβλιοθήκη `paramiko` μέσα στο τοπικό `.venv` για να εκτελεί εντολές στο Home Assistant.
- **Μη χρησιμοποιείτε PowerShell string escaping για πολύπλοκες εντολές.** Γράψτε την εντολή (π.χ. bash/SQL script) σε ένα τοπικό αρχείο, κάντε το Base64 encode, στείλτε το μέσω του `ssh_run.py` στο `/tmp/` του server, και εκτελέστε το εκεί.

## 2. Πρόσβαση στη Βάση Δεδομένων (MariaDB)
- Το Home Assistant χρησιμοποιεί το addon MariaDB, με το hostname `core-mariadb`.
- Η πρόσβαση στη βάση μέσω SSH γίνεται με την εντολή:
  `mysql -h core-mariadb -u homeassistant -pRene1122 homeassistant -e "QUERY..."`
- Πίνακας `statistics_meta`: Περιέχει την αντιστοίχιση των entities (π.χ. `sensor.kuga_energy_daily`) σε `metadata_id`.
- Πίνακας `statistics`: Περιέχει τα ωριαία στατιστικά (`start_ts`, `state`, `sum`, `min`, `max`, `mean`). Το `start_ts` είναι UNIX timestamp (UTC) και αντιστοιχεί στην ΕΝΑΡΞΗ της ώρας καταγραφής.

## 3. Utility Meters & "Phantom Bars" στα Γραφήματα
- **Το Πρόβλημα:** Όταν ένας μετρητής (Utility Meter) μηδενίζει (π.χ. στις 00:00 για ημερήσιο κύκλο), χρειάζεται λίγα ms. Ως αποτέλεσμα, η engine των στατιστικών καταγράφει την "παλιά" μέγιστη τιμή (`max`) μέσα στο bucket `00:00:00 - 01:00:00` της **νέας** μέρας.
- Αν ένα γράφημα στο Lovelace Dashboard χρησιμοποιεί `stat_types: max` για αυτούς τους αισθητήρες, τότε η πρώτη μπάρα της νέας μέρας (Σήμερα) θα εμφανίζει λανθασμένα ("φάντασμα") τη συνολική κατανάλωση της **χθεσινής** μέρας!
- **Η Λύση:** 
  1. Ο αισθητήρας πρέπει να ρυθμιστεί με `state_class: total_increasing` (είτε στο YAML είτε απευθείας στο `.storage/core.config_entries`).
  2. Το γράφημα (`statistics-graph`) στο dashboard ΔΕΝ πρέπει να χρησιμοποιεί `stat_types: max`, αλλά `stat_types: change` (ή να αφεθεί κενό για το default behavior των `total_increasing` αισθητήρων που είναι το `change`).
  3. Το `total_increasing` επιτρέπει στον μετρητή να πέφτει στο 0, καθώς η engine καταλαβαίνει ότι ξεκίνησε νέος κύκλος, και αθροίζει σωστά το `sum` χωρίς να χρειάζεται `min/max/mean`.

## 4. Αλλαγή Πηγής (Source) σε Utility Meter & API Calibration
- Όταν αλλάζετε το `source` ενός Utility Meter (μέσω `.storage/core.config_entries`) από έναν μικρό αισθητήρα σε έναν αθροιστικό lifetime αισθητήρα, μετά από restart το HA θα εντοπίσει τεράστια διαφορά (delta) και θα την προσθέσει στον μετρητή!
- **Διόρθωση:** Αν γίνει αυτό το λάθος, το τεράστιο spike πρέπει να αφαιρεθεί manually από τη βάση (MariaDB) αφαιρώντας τη διαφορά από τις στήλες `sum`, `state` (και `min`, `max`, `mean` αν είναι `measurement`).
- Το τρέχον state διορθώνεται μέσω του Home Assistant REST API στο endpoint `/api/services/utility_meter/calibrate`.
- **ΠΡΟΣΟΧΗ:** Μετά το calibration, πρέπει να γίνει **graceful restart** του Home Assistant ώστε το state machine να προλάβει να σώσει (flush) την τιμή στο αρχείο `.storage/core.restore_state`. Αν υπάρξει απότομο crash, το HA θα επαναφέρει το λανθασμένο "spiked" state!

## 5. Αναδρομική Αλλαγή σε total_increasing & το Σφάλμα "null" στα Γραφήματα
- Αν αλλάξετε αναδρομικά το `state_class` ενός αισθητήρα από `measurement` σε `total_increasing` (για να αποφύγετε τα phantom bars της ώρας μηδενισμού), πρέπει να γνωρίζετε ότι τα ιστορικά δεδομένα στους πίνακες `statistics` και `statistics_short_term` ΔΕΝ έχουν συμπληρωμένη τη στήλη `sum` (είναι `NULL`).
- Αυτό προκαλεί πρόβλημα στα γραφήματα Lovelace (statistics-graph με `stat_types: change`), τα οποία θα δείχνουν `null` αφού δεν μπορούν να υπολογίσουν τη διαφορά (`change = new_sum - old_sum`).
- **Λύση:** Πρέπει να εκτελεστεί SQL `UPDATE` στους πίνακες `statistics` και `statistics_short_term` για να συμπληρωθεί το `sum` στα ιστορικά δεδομένα (π.χ. πολλαπλασιάζοντας το `sum` του αντίστοιχου energy utility meter με την τιμή της κιλοβατώρας, και κάνοντας override τα πρώτα "σπασμένα" deltas ώστε να ταιριάζουν με τις καταγεγραμμένες τιμές του χρήστη).

## 6. Linux Voice Assistant & Pipelines
- Το Linux Voice Assistant (LVA) λειτουργεί ως ESPHome Assist Satellite (lva-dca63226cf9d).
- Εάν δεν υπάρχει select entity για να οριστεί το pipeline μέσα από το UI, το LVA χρησιμοποιεί αυτόματα το **προεπιλεγμένο (default)** pipeline του συστήματος.
- Για προγραμματιστική αλλαγή, μπορούμε να προσθέσουμε το νέο pipeline στο /config/.storage/assist_pipeline.pipelines και να ορίσουμε το ID του ως preferred_item, κάνοντας στη συνέχεια επανεκκίνηση το Home Assistant.


## 7. Custom Home Assistant Add-ons
- Ο φάκελος `/addons` του Home Assistant είναι ιδιοκτησίας `root`.
- Για να μεταφέρετε αρχεία ενός νέου local add-on μέσω SSH, πρέπει υποχρεωτικά να εκτελέσετε τις εντολές ως `sudo` (π.χ. `sudo tar -xzf addon.tar.gz`), αλλιώς θα λάβετε `Permission denied`.

## [2026-09-25] SSH Data Transfer & File Writing
- Όταν γράφουμε μεγάλα αρχεία (π.χ. `core.config_entries`) μέσω SSH (Paramiko) στο Home Assistant, η χρήση `echo '...' | base64 -d` αποτυγχάνει με το σφάλμα `Argument list too long`. Η σωστή προσέγγιση είναι να τρέξουμε `base64 -d | sudo tee /path/to/file > /dev/null` και να στείλουμε τα δεδομένα απευθείας στο `stdin.write(encoded)` stream του Paramiko.

## [2026-09-25] Public Utility Scrapers (DEDDIE & EYATH)
- **DEDDIE:** The scheduled outages page uses a simple POST form at \https://siteapps.deddie.gr/Outages2Public/?Length=4\. You can retrieve the HTML table for a specific area by submitting \PrefectureID\ and \MunicipalityID\ (e.g. 23 and 480 for Oraiokastro, Thessaloniki).
- **EYATH:** The new EYATH portal (\portal.eyath.gr\) uses a modern Angular framework where the outage data (βλάβες/διακοπές) is loaded via internal APIs. There is no simple static HTML table to scrape anymore, making automated programmatic fetching significantly harder compared to DEDDIE.

## Lovelace Dashboard Configuration
- When configuring lovelace dashboards in configuration.yaml, the URL path (the key under dashboards:) **must** contain a hyphen (-). For example, use outages-dash: instead of outages:, otherwise HA will consider the config invalid and refuse to restart (or crash).
- Never restart HA blindly without checking /api/config/core/check_config if you modified configuration.yaml.

## [2026-09-25] Do Not Disturb (DND) Hours
- The user specified DND hours for TTS notifications are: 14:00 to 17:30 (Afternoon quiet hours) AND 23:00 to 08:00 (Night quiet hours). Ensure Voice Assistants only speak outside these windows, or text-only fallback is used.
