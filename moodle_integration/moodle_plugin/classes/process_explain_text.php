<?php
// This file is part of Moodle - http://moodle.org/

namespace aiprovider_elttutor;

/**
 * "Explain text" akcija koristi identičnu logiku kao "Generate text"
 * (Moodle interno čuva tekst pod istim 'prompttext' konfiguracijskim
 * ključem) -- isti obrazac kao ugrađeni aiprovider_openai.
 */
class process_explain_text extends process_generate_text {
}
