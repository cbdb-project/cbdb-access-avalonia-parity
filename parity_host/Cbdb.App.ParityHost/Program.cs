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
/// The request body is read from STDIN (one JSON document, NDJSON
/// daemon mode comes in a later commit). The response is written to
/// STDOUT, also as one JSON document. Errors go to STDERR as
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

        try
        {
            if (args.Length < 2)
            {
                throw new ArgumentException(
                    "usage: cbdb-parity-host <service> <sqlite-path>"
                );
            }

            var service = args[0];
            var sqlitePath = args[1];

            // Read the request body off STDIN as a single JSON
            // document. NDJSON streaming mode comes in 5a-4.
            var requestBody = await Console.In.ReadToEndAsync();

            var responseJson = service switch
            {
                "entry"  => await DispatchEntryAsync(sqlitePath, requestBody),
                _        => throw new ArgumentException(
                              $"unknown service '{service}' "
                              + "(supported: entry; more in later commits)"
                          ),
            };

            // Write a single JSON document to STDOUT, no trailing
            // newline (NDJSON-friendly later).
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
    /// Shared <see cref="JsonSerializerOptions"/>. PropertyNameCaseInsensitive=
    /// true matches the Python harness's tendency to use snake_case
    /// or camelCase interchangeably; default Pascal output is fine
    /// because Python json.loads() handles any casing.
    /// </summary>
    private static readonly JsonSerializerOptions _jsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
        WriteIndented = false,
        // Ensure non-ASCII (CJK) chars are emitted verbatim, not as
        // \uXXXX escapes — keeps the wire payload compact and the
        // diff output human-readable.
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };
}
