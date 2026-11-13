// Historical export only: no account, trade or order operations.
#property script_show_inputs
#property strict

input datetime RequestedStart = D'2024.01.01 00:00';
input datetime RequestedEndExclusive = D'2026.11.01 00:00';

string ClockText(const datetime value)
{
   return TimeToString(value, TIME_DATE | TIME_SECONDS);
}

bool PutMeta(const int handle, const string name, const string value)
{
   return FileWrite(handle, name, value) > 0;
}

bool ExportOne(const string symbol, const ENUM_TIMEFRAMES period, const string label)
{
   if(!SymbolSelect(symbol, true))
   {
      PrintFormat("Unavailable symbol %s: error %d", symbol, GetLastError());
      return false;
   }
   datetime cutoff = TimeCurrent(); // Last known broker server quote time; never UTC-assumed.
   if(cutoff <= 0)
   {
      Print("Server quote time unavailable; refusing to infer candle completeness");
      return false;
   }
   int seconds = PeriodSeconds(period);
   MqlRates rates[];
   ResetLastError();
   int copied = CopyRates(symbol, period, RequestedStart, RequestedEndExclusive - 1, rates);
   if(copied <= 0)
   {
      PrintFormat("CopyRates unavailable for %s %s: result %d error %d. History may still be loading; retry manually.",
                  symbol, label, copied, GetLastError());
      return false;
   }
   string name = StringFormat("PQTA_%s_%s_%s_%u", symbol, label,
                              TimeToString(TimeLocal(), TIME_DATE), GetTickCount());
   StringReplace(name, ".", "-");
   string csv = name + ".csv";
   string meta = name + ".metadata.csv";
   if(FileIsExist(csv) || FileIsExist(meta))
   {
      PrintFormat("Export filename exists; refusing overwrite: %s", name);
      return false;
   }
   int output = FileOpen(csv, FILE_WRITE | FILE_CSV | FILE_ANSI, ',', CP_UTF8);
   if(output == INVALID_HANDLE)
   {
      PrintFormat("Cannot open %s: error %d", csv, GetLastError());
      return false;
   }
   bool ok = FileWrite(output, "timestamp", "open", "high", "low", "close",
                       "tick_volume", "spread_points", "real_volume") > 0;
   long digits = SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   int count = 0;
   datetime first = 0, last = 0;
   for(int i = 0; i < copied && ok; i++)
   {
      MqlRates bar = rates[i];
      if(bar.time < RequestedStart || bar.time >= RequestedEndExclusive ||
         bar.time + seconds > cutoff)
         continue;
      ok = FileWrite(output, ClockText(bar.time), DoubleToString(bar.open, (int)digits),
                     DoubleToString(bar.high, (int)digits), DoubleToString(bar.low, (int)digits),
                     DoubleToString(bar.close, (int)digits), IntegerToString(bar.tick_volume),
                     IntegerToString(bar.spread), IntegerToString(bar.real_volume)) > 0;
      if(ok)
      {
         if(count == 0) first = bar.time;
         last = bar.time;
         count++;
      }
   }
   FileClose(output);
   if(!ok)
   {
      PrintFormat("Failed while writing %s; incomplete file must not be ingested", csv);
      return false;
   }
   int manifest = FileOpen(meta, FILE_WRITE | FILE_CSV | FILE_ANSI, ',', CP_UTF8);
   if(manifest == INVALID_HANDLE)
   {
      PrintFormat("Cannot write metadata %s: error %d; do not ingest the orphan CSV", meta, GetLastError());
      return false;
   }
   ok = FileWrite(manifest, "field", "value") > 0;
   ok = PutMeta(manifest, "format_version", "mt5-export-v1") && ok;
   ok = PutMeta(manifest, "broker_server", AccountInfoString(ACCOUNT_SERVER)) && ok;
   ok = PutMeta(manifest, "symbol", symbol) && ok;
   ok = PutMeta(manifest, "timeframe", label) && ok;
   ok = PutMeta(manifest, "requested_start", ClockText(RequestedStart)) && ok;
   ok = PutMeta(manifest, "requested_end_exclusive", ClockText(RequestedEndExclusive)) && ok;
   ok = PutMeta(manifest, "actual_first", count > 0 ? ClockText(first) : "") && ok;
   ok = PutMeta(manifest, "actual_last", count > 0 ? ClockText(last) : "") && ok;
   ok = PutMeta(manifest, "exported_at_server", ClockText(cutoff)) && ok;
   ok = PutMeta(manifest, "exported_at_local", ClockText(TimeLocal())) && ok;
   ok = PutMeta(manifest, "row_count", IntegerToString(count)) && ok;
   ok = PutMeta(manifest, "copyrates_returned", IntegerToString(copied)) && ok;
   ok = PutMeta(manifest, "timestamp_semantics", "broker_server_clock_unverified") && ok;
   FileClose(manifest);
   if(!ok)
   {
      PrintFormat("Failed to write %s; do not ingest this export", meta);
      return false;
   }
   PrintFormat("Exported %s %s: %d rows (%d returned by CopyRates). Files: %s and %s. Coverage is not verified.",
               symbol, label, count, copied, csv, meta);
   return true;
}

void OnStart()
{
   if(RequestedStart <= 0 || RequestedEndExclusive <= RequestedStart)
   {
      Print("Invalid requested range: end must be after start");
      return;
   }
   string symbols[] = {"EURUSDm", "XAUUSDm"};
   ENUM_TIMEFRAMES periods[] = {PERIOD_M15, PERIOD_H1, PERIOD_H4};
   string names[] = {"M15", "H1", "H4"};
   for(int s = 0; s < ArraySize(symbols); s++)
      for(int t = 0; t < ArraySize(periods); t++)
         ExportOne(symbols[s], periods[t], names[t]);
   Print("Finished. Inspect Experts log for errors, row counts and partial history.");
}
