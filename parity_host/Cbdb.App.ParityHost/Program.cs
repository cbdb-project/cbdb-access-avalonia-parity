using System.Text;
using System.Text.Json;
using Cbdb.App.Core;
using Cbdb.App.Data;

namespace Cbdb.App.ParityHost;

/// <summary>
/// Cbdb.App.ParityHost — one-shot CLI that dispatches a JSON request
/// to the matching Avalonia upstream service and writes a JSON
/// response.
///
/// Usage:
///
///     cbdb-parity-host &lt;service&gt; &lt;sqlite-path&gt;
///
/// The request body is read from STDIN (one JSON document; for the
/// NDJSON daemon mode added in Phase 7h, invoke with `--daemon`).
/// The response is written to STDOUT, also as one JSON document.
/// Errors go to STDERR as
/// `{"error": "...", "stack": "..."}` and produce a non-zero exit
/// code.
///
/// Per WORK_PLAN.md §Phase 5a, STDIN/STDOUT/STDERR are forced to
/// UTF-8 (no BOM) at startup so CJK fields in CBDB rows round-trip
/// cleanly through the Windows default code page.
/// </summary>
internal static class Program
{
    public static async Task<int> Main(string[] args)
    {
        // Load-bearing on Windows: see WORK_PLAN.md §Phase 5a UTF-8
        // pipe contract. The `false` ctor arg means no BOM.
        var utf8 = new UTF8Encoding(false);
        Console.OutputEncoding = utf8;
        Console.InputEncoding = utf8;

        // Phase 7h — `--daemon` flag enables the NDJSON loop that
        // amortises ~1s cold-start over the suite. One-shot mode
        // stays the default for backwards compatibility and easy
        // manual debugging.
        if (args.Length >= 1 && args[0] == "--daemon")
        {
            return await RunDaemonAsync();
        }

        return await RunOneShotAsync(args);
    }

    /// <summary>
    /// One-shot dispatch: usage is the historical
    /// `cbdb-parity-host &lt;service&gt; &lt;sqlite-path&gt;` with the
    /// request body on STDIN. STDERR on a non-zero exit carries
    /// the `{error, stack}` payload Python wraps as
    /// <c>ParityHostError</c>.
    /// </summary>
    private static async Task<int> RunOneShotAsync(string[] args)
    {
        try
        {
            if (args.Length < 2)
            {
                throw new ArgumentException(
                    "usage: cbdb-parity-host <service> <sqlite-path>  (or --daemon)"
                );
            }

            var service = args[0];
            var sqlitePath = args[1];
            var requestBody = await Console.In.ReadToEndAsync();

            var responseJson = await DispatchAsync(service, sqlitePath, requestBody);

            // Write a single JSON document to STDOUT, no trailing
            // newline (NDJSON daemon mode adds them explicitly).
            Console.Out.Write(responseJson);
            return 0;
        }
        catch (Exception ex)
        {
            // {error, stack} payload on stderr; exit code 1.
            var error = new
            {
                error = ex.Message,
                stack = ex.ToString(),
            };
            Console.Error.Write(JsonSerializer.Serialize(error, _jsonOptions));
            return 1;
        }
    }

    /// <summary>
    /// NDJSON daemon mode. The wire contract:
    ///
    /// <para>
    /// <b>Input</b>: one JSON document per line on STDIN, shaped as
    /// <code>
    /// {"service": "...", "sqlite_path": "...", "request": &lt;arbitrary JSON&gt;}
    /// </code>
    /// EOF on STDIN closes the daemon cleanly with exit 0.
    /// </para>
    ///
    /// <para>
    /// <b>Output</b>: one JSON document per line on STDOUT, either
    /// <code>{"ok": &lt;response JSON document&gt;}</code> on success or
    /// <code>{"error": "...", "stack": "..."}</code> when one
    /// request fails (the daemon keeps serving subsequent frames
    /// rather than crashing on the first failure — that's the
    /// whole point of the mode).
    /// </para>
    ///
    /// <para>
    /// <b>Error handling</b>: a parse error on the request frame
    /// itself (malformed JSON, missing field) is also reported as
    /// a per-frame error and the loop continues. The daemon only
    /// exits abnormally on EOF or an unhandled framework
    /// exception (in which case the Python side resurrects it on
    /// the next call — see <c>ParityHostDaemon</c>).
    /// </para>
    /// </summary>
    private static async Task<int> RunDaemonAsync()
    {
        string? line;
        while ((line = await Console.In.ReadLineAsync()) != null)
        {
            string responseLine;
            try
            {
                var frame = JsonSerializer.Deserialize<DaemonRequestFrame>(
                    line, _jsonOptions
                ) ?? throw new ArgumentException(
                    "daemon frame deserialised to null"
                );
                if (string.IsNullOrEmpty(frame.Service))
                {
                    throw new ArgumentException("daemon frame missing 'service'");
                }
                if (string.IsNullOrEmpty(frame.SqlitePath))
                {
                    throw new ArgumentException("daemon frame missing 'sqlite_path'");
                }

                // The dispatch helpers want a JSON STRING for the
                // request body, not a JsonElement; re-serialise the
                // sub-document. Empty / missing `request` is fine
                // for services that don't read STDIN (dynasty_lookup,
                // place_lookup).
                var requestBody = frame.Request.ValueKind == JsonValueKind.Undefined
                    || frame.Request.ValueKind == JsonValueKind.Null
                    ? "{}"
                    : frame.Request.GetRawText();

                var responseJson = await DispatchAsync(
                    frame.Service, frame.SqlitePath, requestBody
                );
                // Wrap in {"ok": ...} so the Python side can
                // distinguish success from error frames cheaply
                // without parsing the response JSON twice.
                using var ms = new System.IO.MemoryStream();
                await using (var w = new Utf8JsonWriter(ms))
                {
                    w.WriteStartObject();
                    w.WritePropertyName("ok");
                    using (var doc = JsonDocument.Parse(responseJson))
                    {
                        doc.RootElement.WriteTo(w);
                    }
                    w.WriteEndObject();
                }
                responseLine = Encoding.UTF8.GetString(ms.ToArray());
            }
            catch (Exception ex)
            {
                var error = new
                {
                    error = ex.Message,
                    stack = ex.ToString(),
                };
                responseLine = JsonSerializer.Serialize(error, _jsonOptions);
            }

            Console.Out.WriteLine(responseLine);
            // Critical on Windows + buffered stdout: without an
            // explicit flush after each frame, the Python side
            // would block on ReadLine() waiting for the OS to
            // flush the pipe buffer (which typically only happens
            // on process exit). Daemon mode is unusable without
            // this.
            await Console.Out.FlushAsync();
        }
        return 0;
    }

    /// <summary>
    /// Per-frame wire shape for daemon mode. `Request` is a raw
    /// JSON sub-document so we can hand it to the same dispatch
    /// helpers that the one-shot path uses — they want a
    /// JSON-string body, not a parsed object.
    /// </summary>
    private sealed record DaemonRequestFrame(
        string Service,
        string SqlitePath,
        JsonElement Request
    );

    /// <summary>
    /// The single dispatch table. Extracted from <see cref="Main"/>
    /// so both <see cref="RunOneShotAsync"/> and
    /// <see cref="RunDaemonAsync"/> share it. Returns the response
    /// as a JSON string ready for the wire (no trailing newline;
    /// the caller adds NDJSON framing if needed).
    /// </summary>
    private static async Task<string> DispatchAsync(
        string service, string sqlitePath, string requestBody)
    {
        // Helper: parse person_id off STDIN once per accessor.
        async Task<string> PersonAccessor<TResult>(
            Func<SqlitePersonBrowserService, int, Task<TResult>> invoker)
        {
            var pr = JsonSerializer.Deserialize<PersonRequest>(
                requestBody, _jsonOptions
            ) ?? throw new ArgumentException(
                "request body could not be deserialised into {person_id}"
            );
            var svc = new SqlitePersonBrowserService();
            var res = await invoker(svc, pr.PersonId);
            return JsonSerializer.Serialize(res, _jsonOptions);
        }

        return service switch
        {
            "entry"          => await DispatchEntryAsync(sqlitePath, requestBody),
            "office"         => await DispatchOfficeAsync(sqlitePath, requestBody),
            "status"         => await DispatchStatusAsync(sqlitePath, requestBody),
            "kinships"       => await DispatchKinshipsAsync(sqlitePath, requestBody),
            // PersonBrowser per-person accessors — all take just
            // (sqlitePath, personId) and return IReadOnlyList<…>.
            // Local generic helper above handles the JSON
            // deserialisation; each branch supplies the
            // service-method invocation.
            "addresses"      => await PersonAccessor((svc, pid) => svc.GetAddressesAsync(sqlitePath, pid)),
            "altnames"       => await PersonAccessor((svc, pid) => svc.GetAltNamesAsync(sqlitePath, pid)),
            "writings"       => await PersonAccessor((svc, pid) => svc.GetWritingsAsync(sqlitePath, pid)),
            "postings"       => await PersonAccessor((svc, pid) => svc.GetPostingsAsync(sqlitePath, pid)),
            "entries"        => await PersonAccessor((svc, pid) => svc.GetEntriesAsync(sqlitePath, pid)),
            "statuses"       => await PersonAccessor((svc, pid) => svc.GetStatusesAsync(sqlitePath, pid)),
            "possessions"    => await PersonAccessor((svc, pid) => svc.GetPossessionsAsync(sqlitePath, pid)),
            "events"         => await PersonAccessor((svc, pid) => svc.GetEventsAsync(sqlitePath, pid)),
            "associations"   => await PersonAccessor((svc, pid) => svc.GetAssociationsAsync(sqlitePath, pid)),
            "sources"        => await PersonAccessor((svc, pid) => svc.GetSourcesAsync(sqlitePath, pid)),
            "institutions"   => await PersonAccessor((svc, pid) => svc.GetInstitutionsAsync(sqlitePath, pid)),
            // GetDetailAsync returns PersonDetail? (nullable scalar),
            // not a list — but the same PersonRequest shape works.
            "detail"         => await PersonAccessor((svc, pid) => svc.GetDetailAsync(sqlitePath, pid)),
            // BIOG basic search — (keyword, limit, offset).
            "biog_basic"     => await DispatchBiogBasicAsync(sqlitePath, requestBody),
            // Phase 5e lookup surfaces — added once the SDK was
            // available so the harness can drive the same options
            // builders the Avalonia UI uses.
            "dynasty_lookup" => await DispatchDynastyLookupAsync(sqlitePath),
            "place_lookup"   => await DispatchPlaceLookupAsync(sqlitePath),
            "group_people"   => await DispatchGroupPeopleAsync(sqlitePath, requestBody),
            _                => throw new ArgumentException(
                                  $"unknown service '{service}' "
                                  + "(supported: entry, office, status, kinships, "
                                  + "addresses, altnames, writings, postings, entries, "
                                  + "statuses, possessions, events, associations, "
                                  + "sources, institutions, detail, biog_basic, "
                                  + "dynasty_lookup, place_lookup, group_people)"
                              ),
        };
    }

    /// <summary>
    /// Dispatch an Entry query: deserialise the JSON request body
    /// into the upstream <see cref="EntryQueryRequest"/>, invoke
    /// <see cref="SqliteEntryQueryService.QueryAsync"/>, and
    /// serialise the resulting <see cref="EntryQueryResult"/>.
    /// </summary>
    private static async Task<string> DispatchEntryAsync(
        string sqlitePath, string requestBody)
    {
        var request = JsonSerializer.Deserialize<EntryQueryRequest>(
            requestBody, _jsonOptions
        ) ?? throw new ArgumentException(
            "entry: request body could not be deserialised into EntryQueryRequest"
        );

        var service = new SqliteEntryQueryService();
        var result = await service.QueryAsync(sqlitePath, request);
        return JsonSerializer.Serialize(result, _jsonOptions);
    }

    /// <summary>
    /// Dispatch an Office query.
    /// </summary>
    private static async Task<string> DispatchOfficeAsync(
        string sqlitePath, string requestBody)
    {
        var request = JsonSerializer.Deserialize<OfficeQueryRequest>(
            requestBody, _jsonOptions
        ) ?? throw new ArgumentException(
            "office: request body could not be deserialised into OfficeQueryRequest"
        );

        var service = new SqliteOfficeQueryService();
        var result = await service.QueryAsync(sqlitePath, request);
        return JsonSerializer.Serialize(result, _jsonOptions);
    }

    /// <summary>
    /// Dispatch a Status query.
    /// </summary>
    private static async Task<string> DispatchStatusAsync(
        string sqlitePath, string requestBody)
    {
        var request = JsonSerializer.Deserialize<StatusQueryRequest>(
            requestBody, _jsonOptions
        ) ?? throw new ArgumentException(
            "status: request body could not be deserialised into StatusQueryRequest"
        );

        var service = new SqliteStatusQueryService();
        var result = await service.QueryAsync(sqlitePath, request);
        return JsonSerializer.Serialize(result, _jsonOptions);
    }

    /// <summary>
    /// Dispatch <see cref="SqlitePersonBrowserService.GetKinshipsAsync"/>
    /// — the BFS state machine when <c>expand_network=true</c>, or the
    /// direct kinship list when <c>expand_network=false</c>.
    /// Phase 5d's mirror-vs-host cross-check uses this.
    ///
    /// Request shape (snake_case JSON):
    /// <code>{"person_id": int, "expand_network": bool}</code>
    /// Response: JSON array of PersonKinshipItem (the C# return type).
    /// </summary>
    private static async Task<string> DispatchKinshipsAsync(
        string sqlitePath, string requestBody)
    {
        var request = JsonSerializer.Deserialize<KinshipsRequest>(
            requestBody, _jsonOptions
        ) ?? throw new ArgumentException(
            "kinships: request body could not be deserialised into "
            + "{person_id, expand_network}"
        );

        var service = new SqlitePersonBrowserService();
        var result = await service.GetKinshipsAsync(
            sqlitePath,
            request.PersonId,
            expandNetwork: request.ExpandNetwork
        );
        return JsonSerializer.Serialize(result, _jsonOptions);
    }

    /// <summary>
    /// Local DTO mirroring the (person_id, expand_network) shape the
    /// kinships dispatch reads off STDIN. Kept here rather than in
    /// Cbdb.App.Core because it's wire-format glue, not an Avalonia
    /// query record.
    /// </summary>
    private sealed record KinshipsRequest(
        int PersonId,
        bool ExpandNetwork = false
    );

    /// <summary>
    /// Local DTO for all per-person accessors that take just
    /// <c>{person_id}</c> off STDIN.
    /// </summary>
    private sealed record PersonRequest(int PersonId);

    /// <summary>
    /// Local DTO for the BIOG-basic SearchAsync — matches the
    /// (keyword, limit, offset) shape of <c>SearchAsync</c>.
    /// </summary>
    private sealed record BiogBasicRequest(
        string? Keyword = null,
        int Limit = 200,
        int Offset = 0
    );

    /// <summary>
    /// Dispatch <c>SqlitePersonBrowserService.SearchAsync</c> — the
    /// "BIOG basic" search. Distinct shape from the per-person
    /// accessors: takes <c>(keyword, limit, offset)</c> instead of
    /// a person_id.
    /// </summary>
    private static async Task<string> DispatchBiogBasicAsync(
        string sqlitePath, string requestBody)
    {
        var request = JsonSerializer.Deserialize<BiogBasicRequest>(
            requestBody, _jsonOptions
        ) ?? throw new ArgumentException(
            "biog_basic: request body could not be deserialised into "
            + "{keyword, limit, offset}"
        );

        var service = new SqlitePersonBrowserService();
        var result = await service.SearchAsync(
            sqlitePath, request.Keyword, request.Limit, request.Offset
        );
        return JsonSerializer.Serialize(result, _jsonOptions);
    }

    /// <summary>
    /// Dispatch <c>SqliteDynastyLookupService.GetDynastiesAsync</c> —
    /// returns the dynasty option list the UI uses to populate
    /// dropdowns. Phase 5e.
    /// </summary>
    private static async Task<string> DispatchDynastyLookupAsync(string sqlitePath)
    {
        var service = new SqliteDynastyLookupService();
        var result = await service.GetDynastiesAsync(sqlitePath);
        return JsonSerializer.Serialize(result, _jsonOptions);
    }

    /// <summary>
    /// Dispatch <c>SqlitePlaceLookupService.GetPlacesAsync</c>. Phase 5e.
    /// </summary>
    private static async Task<string> DispatchPlaceLookupAsync(string sqlitePath)
    {
        var service = new SqlitePlaceLookupService();
        var result = await service.GetPlacesAsync(sqlitePath);
        return JsonSerializer.Serialize(result, _jsonOptions);
    }

    /// <summary>
    /// Dispatch <c>SqliteGroupPeopleService.QueryAsync</c> — multi-person
    /// composite. Wire shape: <code>{"person_ids":[...], "options":{...}}</code>
    /// where options matches <see cref="GroupPeopleQueryOptions"/>
    /// (include_status / include_office / include_entry / include_texts /
    /// include_addresses / address_mode). Phase 5e.
    /// </summary>
    private static async Task<string> DispatchGroupPeopleAsync(
        string sqlitePath, string requestBody)
    {
        var request = JsonSerializer.Deserialize<GroupPeopleRequest>(
            requestBody, _jsonOptions
        ) ?? throw new ArgumentException(
            "group_people: request body could not be deserialised into "
            + "{person_ids, options}"
        );
        var service = new SqliteGroupPeopleService();
        var result = await service.QueryAsync(
            sqlitePath, request.PersonIds, request.Options
        );
        return JsonSerializer.Serialize(result, _jsonOptions);
    }

    /// <summary>
    /// Wire shape for <see cref="DispatchGroupPeopleAsync"/>. We keep
    /// it local rather than introduce a new Cbdb.App.Core record per
    /// the §0 scope contract (this repo does not modify upstream).
    /// </summary>
    private sealed record GroupPeopleRequest(
        IReadOnlyList<int> PersonIds,
        GroupPeopleQueryOptions Options
    );

    /// <summary>
    /// Shared <see cref="JsonSerializerOptions"/>.
    ///
    /// <para>
    /// <b>PropertyNamingPolicy = SnakeCaseLower</b>: the wire contract is
    /// snake_case in both directions, matching Python idiom
    /// (`dataclasses.asdict()` + `json.dumps()` already produces
    /// snake_case). So <c>{"entry_codes": ["36"]}</c> deserialises into
    /// <c>EntryQueryRequest.EntryCodes</c>, and serialised
    /// <c>EntryQueryResult.Records</c> writes back as <c>records</c>.
    /// PropertyNameCaseInsensitive alone does NOT bridge the underscore
    /// difference — without the policy, snake_case input silently
    /// constructs the record with default values and later crashes in
    /// <c>SqliteEntryQueryService.QueryAsync</c> on
    /// <c>request.DynastyIds.Count</c> (NRE on a null
    /// <c>IReadOnlyList&lt;int&gt;</c>). Codex round-1 caught this.
    /// </para>
    /// <para>
    /// <b>UnsafeRelaxedJsonEscaping</b>: emit non-ASCII (CJK) chars
    /// verbatim instead of <c>\uXXXX</c> escapes, keeping the wire
    /// payload compact and diff output readable.
    /// </para>
    /// </summary>
    private static readonly JsonSerializerOptions _jsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        WriteIndented = false,
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };
}
