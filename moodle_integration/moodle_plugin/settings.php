<?php
// This file is part of Moodle - http://moodle.org/

defined('MOODLE_INTERNAL') || die();

if ($hassiteconfig) {
    $settings->add(new admin_setting_configtext(
        'aiprovider_elttutor/apiendpoint',
        new lang_string('apiendpoint', 'aiprovider_elttutor'),
        new lang_string('apiendpoint_desc', 'aiprovider_elttutor'),
        'http://localhost:8100',
        PARAM_URL
    ));
}
