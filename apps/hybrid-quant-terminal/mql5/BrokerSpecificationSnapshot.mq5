// Read-only broker metadata snapshot. No order, account-setting or trade APIs.
// Run manually on a connected Exness demo terminal. Output remains UNVERIFIED.
#property script_show_inputs
#property strict

bool output_ok=true;
void WriteCsv(const int file,const string instrument,const string property,
              const string value,const string status)
{
   if(FileWrite(file,instrument,property,value,status)==0) output_ok=false;
}

void WriteDouble(const int file,const string symbol,const string name,
                 const ENUM_SYMBOL_INFO_DOUBLE property)
{
   double value=0.0;
   ResetLastError();
   bool ok=SymbolInfoDouble(symbol,property,value);
   int error=GetLastError();
   if(ok && MathIsValidNumber(value))
      WriteCsv(file,symbol,name,DoubleToString(value,12),"observed");
   else
      WriteCsv(file,symbol,name,"","unavailable:"+IntegerToString(error));
}

void WriteInteger(const int file,const string symbol,const string name,
                  const ENUM_SYMBOL_INFO_INTEGER property)
{
   long value=0;
   ResetLastError();
   bool ok=SymbolInfoInteger(symbol,property,value);
   int error=GetLastError();
   if(ok) WriteCsv(file,symbol,name,IntegerToString(value),"observed");
   else WriteCsv(file,symbol,name,"","unavailable:"+IntegerToString(error));
}

void WriteString(const int file,const string symbol,const string name,
                 const ENUM_SYMBOL_INFO_STRING property)
{
   string value="";
   ResetLastError();
   bool ok=SymbolInfoString(symbol,property,value);
   int error=GetLastError();
   if(ok && value!="") WriteCsv(file,symbol,name,value,"observed");
   else WriteCsv(file,symbol,name,"","unavailable:"+IntegerToString(error));
}

void Snapshot(const int file,const string symbol)
{
   WriteInteger(file,symbol,"selected",SYMBOL_SELECT);
   WriteCsv(file,symbol,"synchronized",SymbolIsSynchronized(symbol)?"1":"0","observed");
   WriteDouble(file,symbol,"contract_size",SYMBOL_TRADE_CONTRACT_SIZE);
   WriteInteger(file,symbol,"digits",SYMBOL_DIGITS);
   WriteDouble(file,symbol,"point",SYMBOL_POINT);
   WriteDouble(file,symbol,"tick_size",SYMBOL_TRADE_TICK_SIZE);
   WriteDouble(file,symbol,"tick_value",SYMBOL_TRADE_TICK_VALUE);
   WriteDouble(file,symbol,"tick_value_profit",SYMBOL_TRADE_TICK_VALUE_PROFIT);
   WriteDouble(file,symbol,"tick_value_loss",SYMBOL_TRADE_TICK_VALUE_LOSS);
   WriteDouble(file,symbol,"volume_min",SYMBOL_VOLUME_MIN);
   WriteDouble(file,symbol,"volume_max",SYMBOL_VOLUME_MAX);
   WriteDouble(file,symbol,"volume_step",SYMBOL_VOLUME_STEP);
   WriteDouble(file,symbol,"volume_limit",SYMBOL_VOLUME_LIMIT);
   WriteInteger(file,symbol,"profit_calculation_mode",SYMBOL_TRADE_CALC_MODE);
   WriteInteger(file,symbol,"trade_mode",SYMBOL_TRADE_MODE);
   WriteCsv(file,symbol,"margin_calculation_mode","","unavailable_not_inferred");
   WriteInteger(file,symbol,"stops_level_points",SYMBOL_TRADE_STOPS_LEVEL);
   WriteInteger(file,symbol,"freeze_level_points",SYMBOL_TRADE_FREEZE_LEVEL);
   WriteInteger(file,symbol,"spread_points",SYMBOL_SPREAD);
   WriteString(file,symbol,"base_currency",SYMBOL_CURRENCY_BASE);
   WriteString(file,symbol,"profit_currency",SYMBOL_CURRENCY_PROFIT);
   WriteString(file,symbol,"margin_currency",SYMBOL_CURRENCY_MARGIN);
   WriteDouble(file,symbol,"swap_long",SYMBOL_SWAP_LONG);
   WriteDouble(file,symbol,"swap_short",SYMBOL_SWAP_SHORT);
   MqlTick tick;
   ResetLastError();
   if(SymbolInfoTick(symbol,tick))
   {
      WriteCsv(file,symbol,"bid",DoubleToString(tick.bid,12),"observed_quote_not_verified_fresh");
      WriteCsv(file,symbol,"ask",DoubleToString(tick.ask,12),"observed_quote_not_verified_fresh");
      WriteCsv(file,symbol,"tick_broker_time",TimeToString(tick.time,TIME_DATE|TIME_SECONDS),"broker_time_timezone_unverified");
   }
   else
   {
      int error=GetLastError();
      WriteCsv(file,symbol,"bid","","unavailable:"+IntegerToString(error));
      WriteCsv(file,symbol,"ask","","unavailable:"+IntegerToString(error));
   }
   WriteCsv(file,symbol,"commission","","unavailable_not_inferred");
   WriteCsv(file,symbol,"session_constraints","","unavailable_not_inferred");
   WriteCsv(file,symbol,"margin_estimate","","unavailable_not_calculated");
}

void OnStart()
{
   string server=AccountInfoString(ACCOUNT_SERVER);
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO ||
      StringFind(server,"Exness")<0 || !TerminalInfoInteger(TERMINAL_CONNECTED))
   {
      Print("Snapshot refused: connected Exness demo terminal required.");
      return;
   }
   string filename="broker_spec_snapshot_"+IntegerToString((long)TimeLocal())+
                   "_"+IntegerToString((long)GetTickCount64())+".csv";
   if(FileIsExist(filename)) { Print("Snapshot refused: destination exists."); return; }
   ResetLastError();
   string temporary=filename+".partial";
   if(FileIsExist(temporary)) { Print("Snapshot refused: temporary file exists."); return; }
   int file=FileOpen(temporary,FILE_WRITE|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   if(file==INVALID_HANDLE) { Print("Snapshot open failed: ",GetLastError()); return; }
   WriteCsv(file,"instrument","property","value","status");
   WriteCsv(file,"","server",server,"self_reported_not_authenticated");
   WriteCsv(file,"","account_type","demo","terminal_reported");
   ResetLastError();
   string currency=AccountInfoString(ACCOUNT_CURRENCY);
   if(currency!="") WriteCsv(file,"","account_currency",currency,"terminal_reported");
   else WriteCsv(file,"","account_currency","","unavailable:"+IntegerToString(GetLastError()));
   WriteCsv(file,"","broker_observed_at",TimeToString(TimeCurrent(),TIME_DATE|TIME_SECONDS),"broker_time_timezone_unverified");
   WriteCsv(file,"","host_observed_at",TimeToString(TimeLocal(),TIME_DATE|TIME_SECONDS),"host_clock_not_authenticated");
   Snapshot(file,"EURUSDm");
   Snapshot(file,"XAUUSDm");
   FileFlush(file);
   FileClose(file);
   if(!output_ok) { Print("Snapshot incomplete; retained partial file: ",temporary); return; }
   if(!FileMove(temporary,0,filename,0))
   {
      Print("Snapshot publish failed: ",GetLastError(),"; partial file: ",temporary);
      return;
   }
   Print("Read-only broker specification snapshot saved under MQL5/Files: ",filename,
         "; values require independent verification.");
}
