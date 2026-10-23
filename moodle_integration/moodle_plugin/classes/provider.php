<?php
// This file is part of Moodle - http://moodle.org/

namespace aiprovider_elttutor;

/**
 * Provider koji povezuje Moodle AI Subsystem s vlastitim LangGraph
 * tutor agentom (diplomski rad -- usporedba agentnih arhitektura).
 *
 * Provider je namjerno "tanak": ne sadrži pedagošku logiku niti UI --
 * samo prosljeđuje zahtjeve prema FastAPI servisu
 * (moodle_integration/api/moodle_api.py) koji poziva stvarnog agenta.
 */
class provider extends \core_ai\provider {

    /**
     * Vraća listu akcija koje ovaj provider podržava. "Course assistance
     * placement" (aktiviran u Moodle-u) koristi explain_text i
     * summarise_text, ne generate_text -- zato su sve tri ovdje.
     */
    public static function get_action_list(): array {
        return [
            \core_ai\aiactions\generate_text::class,
            \core_ai\aiactions\explain_text::class,
            \core_ai\aiactions\summarise_text::class,
        ];
    }

    public function is_provider_configured(): bool {
        return !empty($this->config['apiendpoint']);
    }
}
