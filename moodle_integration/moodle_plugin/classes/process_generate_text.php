<?php
// This file is part of Moodle - http://moodle.org/

namespace aiprovider_elttutor;

use GuzzleHttp\Psr7\Request;
use Psr\Http\Message\RequestInterface;
use Psr\Http\Message\ResponseInterface;

/**
 * Obrađuje Moodle-ov "generate_text" zahtjev -- gradi HTTP zahtjev prema
 * FastAPI servisu (moodle_api.py) i parsira odgovor natrag u oblik koji
 * Moodle AI Subsystem očekuje.
 */
class process_generate_text extends abstract_processor {

    #[\Override]
    protected function create_request_object(string $userid): RequestInterface {
        $body = json_encode([
            'prompttext' => $this->action->get_configuration('prompttext'),
        ]);

        // uri: '' -- prazno namjerno, poziv ide direktno na base_uri
        // (puna adresa /generate endpointa, vidi get_endpoint()).
        return new Request(
            method: 'POST',
            uri: '',
            headers: ['Content-Type' => 'application/json'],
            body: $body,
        );
    }

    #[\Override]
    protected function handle_api_success(ResponseInterface $response): array {
        $bodyobj = json_decode($response->getBody()->getContents());
        return [
            'success' => true,
            'generatedcontent' => $bodyobj->generatedcontent ?? '',
            'finishreason' => $bodyobj->finishreason ?? 'stop',
        ];
    }
}
