<?php
// This file is part of Moodle - http://moodle.org/

namespace aiprovider_elttutor;

use core\http_client;
use core_ai\process_base;
use GuzzleHttp\Exception\RequestException;
use GuzzleHttp\Psr7\Uri;
use GuzzleHttp\RequestOptions;
use Psr\Http\Message\RequestInterface;
use Psr\Http\Message\ResponseInterface;
use Psr\Http\Message\UriInterface;

/**
 * Zajednička bazna klasa za sve akcije ovog providera. Generička
 * implementacija query_ai_api() prati isti obrazac kao aiprovider_openai
 * -- poziva create_request_object() (definisano po akciji, npr. u
 * process_generate_text), izvršava HTTP poziv, i prosljeđuje odgovor u
 * handle_api_success()/handle_api_error().
 */
abstract class abstract_processor extends process_base {

    /**
     * Adresa FastAPI servisa (moodle_integration/api/moodle_api.py),
     * unesena kod kreiranja instance providera (vidi hook_listener.php).
     */
    protected function get_endpoint(): UriInterface {
        return new Uri($this->provider->config['apiendpoint']);
    }

    abstract protected function create_request_object(string $userid): RequestInterface;

    abstract protected function handle_api_success(ResponseInterface $response): array;

    #[\Override]
    protected function query_ai_api(): array {
        $request = $this->create_request_object(
            userid: $this->provider->generate_userid($this->action->get_configuration('userid')),
        );
        $request = $this->provider->add_authentication_headers($request);

        $client = \core\di::get(http_client::class);
        try {
            $response = $client->send($request, [
                'base_uri' => $this->get_endpoint(),
                RequestOptions::HTTP_ERRORS => false,
            ]);
        } catch (RequestException $e) {
            return \core_ai\error\factory::create($e->getCode(), $e->getMessage())->get_error_details();
        }

        $status = $response->getStatusCode();
        if ($status === 200) {
            return $this->handle_api_success($response);
        } else {
            return $this->handle_api_error($response);
        }
    }

    protected function handle_api_error(ResponseInterface $response): array {
        $status = $response->getStatusCode();
        $errormessage = $response->getReasonPhrase();
        return \core_ai\error\factory::create($status, $errormessage)->get_error_details();
    }
}
