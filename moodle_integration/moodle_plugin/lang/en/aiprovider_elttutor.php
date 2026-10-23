<?php
// This file is part of Moodle - http://moodle.org/

defined('MOODLE_INTERNAL') || die();

$string['pluginname'] = 'ELT Tutor (diplomski rad)';
$string['apiendpoint'] = 'API endpoint';
$string['apiendpoint_help'] = 'Puna adresa /generate endpointa FastAPI servisa koji poziva LangGraph tutor agenta (npr. http://host.docker.internal:8100/generate ako Moodle radi u Docker kontejneru, a servis na host mašini). Vidi moodle_integration/api/moodle_api.py u repozitoriju diplomskog rada.';
$string['privacy:metadata'] = 'Ovaj plugin prosljeđuje tekst upita vanjskom API servisu radi generisanja odgovora; ne pohranjuje podatke lokalno.';
