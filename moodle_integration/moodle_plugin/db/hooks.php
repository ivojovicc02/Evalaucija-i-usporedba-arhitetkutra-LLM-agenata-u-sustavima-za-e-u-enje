<?php
// This file is part of Moodle - http://moodle.org/

/**
 * Hook listener callbacks za ELT Tutor provider.
 *
 * @package    aiprovider_elttutor
 */

defined('MOODLE_INTERNAL') || die();

$callbacks = [
    [
        'hook' => \core_ai\hook\after_ai_provider_form_hook::class,
        'callback' => \aiprovider_elttutor\hook_listener::class . '::set_form_definition_for_aiprovider_elttutor',
    ],
];
