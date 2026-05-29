using System.Text;

namespace Cbdb.App.ParityHost;

/// <summary>
/// Scaffold entry point. Future commits will add the dispatch
/// branches per WORK_PLAN.md §Phase 5a. For now this is a smoke
/// binary that proves the cross-repo ProjectReference + UTF-8
/// pipe setup work end-to-end.
/// </summary>
internal static class Program
{
    public static int Main(string[] args)
    {
        // Load-bearing on Windows: the default Console.OutputEncoding
        // is the OEM code page (cp936 / cp1252 etc.), which mojibakes
        // the CJK fields in CBDB rows. The Python harness depends on
        // strict UTF-8 to round-trip name_chn / title_chn / etc.
        // The `false` constructor arg means no BOM.
        Console.OutputEncoding = new UTF8Encoding(false);
        Console.InputEncoding = new UTF8Encoding(false);

        // Smoke output: confirms (1) the cross-repo ProjectReference
        // resolved at build time, (2) UTF-8 encoding is in force.
        // Real dispatch comes in the next commit.
        Console.WriteLine("Cbdb.App.ParityHost scaffold OK");
        Console.WriteLine($"args={string.Join(" ", args)}");
        Console.WriteLine("中文 round-trip test 字段名");

        // Touch the upstream types just to prove the references
        // actually link. We don't construct services here.
        _ = typeof(Cbdb.App.Core.EntryQueryRequest);
        _ = typeof(Cbdb.App.Data.SqliteEntryQueryService);

        return 0;
    }
}
