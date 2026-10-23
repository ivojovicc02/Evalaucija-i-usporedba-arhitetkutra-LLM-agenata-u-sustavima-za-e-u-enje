<?php
// This file is part of Moodle - http://moodle.org/

namespace aiprovider_elttutor;

use core_ai\hook\after_ai_provider_form_hook;

/**
 * Hook listener za ELT Tutor provider -- dodaje polje za API endpoint
 * u generičku formu "Create new provider instance", istim mehanizmom
 * kojim ugrađeni aiprovider_openai dodaje polje 'apikey'.
 */
class hook_listener {

    /**
     * Dodaje polje 'apiendpoint' u formu za podešavanje instance providera.
     *
     * @param after_ai_provider_form_hook $hook
     */
    public static function set_form_definition_for_aiprovider_elttutor(after_ai_provider_form_hook $hook): void {
        if ($hook->plugin !== 'aiprovider_elttutor') {
            return;
        }

        $mform = $hook->mform;

        $mform->addElement(
            'text',
            'apiendpoint',
            get_string('apiendpoint', 'aiprovider_elttutor'),
            ['size' => 75],
        );
        $mform->setType('apiendpoint', PARAM_URL);
        $mform->addHelpButton('apiendpoint', 'apiendpoint', 'aiprovider_elttutor');
        $mform->addRule('apiendpoint', get_string('required'), 'required', null, 'client');
        $mform->setDefault('apiendpoint', 'http://host.docker.internal:8100/generate');
    }
}
