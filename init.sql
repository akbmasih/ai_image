-- /ai/init.sql
-- PostgreSQL initialization script for AI server database setup with complete plugin support

-- Create database if not exists (usually handled by Docker)
-- CREATE DATABASE ai_db;

-- Create user if not exists (usually handled by Docker)
-- CREATE USER ai_user WITH PASSWORD 'ai_password';

-- Grant permissions to ai_user
GRANT ALL PRIVILEGES ON DATABASE ai_db TO ai_user;
GRANT ALL PRIVILEGES ON SCHEMA public TO ai_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO ai_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO ai_user;

-- Enable necessary extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_stat_statements";

-- Create index template function for future plugin tables
CREATE OR REPLACE FUNCTION create_plugin_indexes(table_name TEXT)
RETURNS VOID AS $$
BEGIN
    EXECUTE format('CREATE INDEX IF NOT EXISTS idx_%s_cache_key ON %s(cache_key)', 
                   replace(table_name, 'cache_', ''), table_name);
    EXECUTE format('CREATE INDEX IF NOT EXISTS idx_%s_user_id ON %s(user_id)', 
                   replace(table_name, 'cache_', ''), table_name);
    EXECUTE format('CREATE INDEX IF NOT EXISTS idx_%s_created_at ON %s(created_at)', 
                   replace(table_name, 'cache_', ''), table_name);
    EXECUTE format('CREATE INDEX IF NOT EXISTS idx_%s_accessed_at ON %s(accessed_at)', 
                   replace(table_name, 'cache_', ''), table_name);
    EXECUTE format('CREATE INDEX IF NOT EXISTS idx_%s_user_created ON %s(user_id, created_at)', 
                   replace(table_name, 'cache_', ''), table_name);
END;
$$ LANGUAGE plpgsql;

-- Create cache tables for all supported plugins
CREATE TABLE IF NOT EXISTS cache_chatgpt (
    id SERIAL PRIMARY KEY,
    cache_key VARCHAR(255) UNIQUE NOT NULL,
    request_data JSONB NOT NULL,
    response_data JSONB NOT NULL,
    user_id VARCHAR(10) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cache_flux (
    id SERIAL PRIMARY KEY,
    cache_key VARCHAR(255) UNIQUE NOT NULL,
    request_data JSONB NOT NULL,
    response_data JSONB NOT NULL,
    user_id VARCHAR(10) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cache_chatterbox (
    id SERIAL PRIMARY KEY,
    cache_key VARCHAR(255) UNIQUE NOT NULL,
    request_data JSONB NOT NULL,
    response_data JSONB NOT NULL,
    user_id VARCHAR(10) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for all plugin tables
SELECT create_plugin_indexes('cache_chatgpt');
SELECT create_plugin_indexes('cache_flux');
SELECT create_plugin_indexes('cache_chatterbox');

-- Create performance monitoring table
CREATE TABLE IF NOT EXISTS ai_server_performance (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    plugin_name VARCHAR(50) NOT NULL,
    endpoint VARCHAR(100) NOT NULL,
    user_id VARCHAR(10),
    processing_time_ms INTEGER,
    cache_hit BOOLEAN DEFAULT FALSE,
    tokens_used INTEGER,
    request_size_bytes INTEGER,
    response_size_bytes INTEGER,
    success BOOLEAN DEFAULT TRUE,
    error_type VARCHAR(50),
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_performance_timestamp ON ai_server_performance(timestamp);
CREATE INDEX IF NOT EXISTS idx_performance_plugin ON ai_server_performance(plugin_name);
CREATE INDEX IF NOT EXISTS idx_performance_user ON ai_server_performance(user_id);
CREATE INDEX IF NOT EXISTS idx_performance_endpoint ON ai_server_performance(endpoint);
CREATE INDEX IF NOT EXISTS idx_performance_cache_hit ON ai_server_performance(cache_hit);

-- Log table for monitoring and debugging
CREATE TABLE IF NOT EXISTS ai_server_logs (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    level VARCHAR(20) NOT NULL,
    plugin_name VARCHAR(50),
    user_id VARCHAR(10),
    message TEXT NOT NULL,
    metadata JSONB,
    request_id UUID DEFAULT gen_random_uuid()
);

CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON ai_server_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_plugin ON ai_server_logs(plugin_name);
CREATE INDEX IF NOT EXISTS idx_logs_user ON ai_server_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_logs_level ON ai_server_logs(level);
CREATE INDEX IF NOT EXISTS idx_logs_request_id ON ai_server_logs(request_id);

-- Create plugin configuration table for dynamic plugin management
CREATE TABLE IF NOT EXISTS plugin_configurations (
    id SERIAL PRIMARY KEY,
    plugin_name VARCHAR(50) UNIQUE NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    configuration JSONB DEFAULT '{}',
    rate_limit_per_minute INTEGER DEFAULT 20,
    cache_enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert default plugin configurations
INSERT INTO plugin_configurations (plugin_name, configuration, rate_limit_per_minute) VALUES
('chatgpt', '{"model": "gpt-4o-mini", "max_tokens": 2000, "temperature": 0.7}', 20),
('flux', '{"model": "flux-1-schnell", "default_width": 1024, "default_height": 1024, "max_steps": 10}', 5),
('chatterbox', '{"model": "chatterbox-tts", "default_language": "en", "default_emotion": "neutral"}', 10)
ON CONFLICT (plugin_name) DO NOTHING;

-- Create cache statistics view for monitoring
CREATE OR REPLACE VIEW cache_statistics AS
SELECT 
    'chatgpt' as plugin_name,
    COUNT(*) as total_entries,
    COUNT(DISTINCT user_id) as unique_users,
    AVG(EXTRACT(EPOCH FROM (accessed_at - created_at))) as avg_cache_age_seconds,
    MAX(accessed_at) as last_access
FROM cache_chatgpt
UNION ALL
SELECT 
    'flux' as plugin_name,
    COUNT(*) as total_entries,
    COUNT(DISTINCT user_id) as unique_users,
    AVG(EXTRACT(EPOCH FROM (accessed_at - created_at))) as avg_cache_age_seconds,
    MAX(accessed_at) as last_access
FROM cache_flux
UNION ALL
SELECT 
    'chatterbox' as plugin_name,
    COUNT(*) as total_entries,
    COUNT(DISTINCT user_id) as unique_users,
    AVG(EXTRACT(EPOCH FROM (accessed_at - created_at))) as avg_cache_age_seconds,
    MAX(accessed_at) as last_access
FROM cache_chatterbox;

-- Create function for cache cleanup (remove entries older than specified days)
CREATE OR REPLACE FUNCTION cleanup_old_cache(plugin_name TEXT, days_old INTEGER DEFAULT 30)
RETURNS INTEGER AS $
DECLARE
    deleted_count INTEGER;
    table_name TEXT;
BEGIN
    table_name := 'cache_' || plugin_name;
    
    EXECUTE format(
        'DELETE FROM %I WHERE created_at < NOW() - INTERVAL ''%s days''',
        table_name, days_old
    );
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    
    -- Log the cleanup operation
    INSERT INTO ai_server_logs (level, plugin_name, message, metadata)
    VALUES ('INFO', plugin_name, 'Cache cleanup completed', 
            json_build_object('deleted_entries', deleted_count, 'days_old', days_old));
    
    RETURN deleted_count;
END;
$ LANGUAGE plpgsql;

-- Create function for performance metrics aggregation
CREATE OR REPLACE FUNCTION get_plugin_performance_metrics(
    plugin_name_param TEXT,
    hours_back INTEGER DEFAULT 24
)
RETURNS TABLE (
    total_requests BIGINT,
    cache_hit_rate NUMERIC,
    avg_processing_time_ms NUMERIC,
    error_rate NUMERIC,
    unique_users BIGINT
) AS $
BEGIN
    RETURN QUERY
    SELECT 
        COUNT(*) as total_requests,
        ROUND(
            (COUNT(*) FILTER (WHERE cache_hit = TRUE)::NUMERIC / 
             NULLIF(COUNT(*), 0) * 100), 2
        ) as cache_hit_rate,
        ROUND(AVG(processing_time_ms), 2) as avg_processing_time_ms,
        ROUND(
            (COUNT(*) FILTER (WHERE success = FALSE)::NUMERIC / 
             NULLIF(COUNT(*), 0) * 100), 2
        ) as error_rate,
        COUNT(DISTINCT user_id) as unique_users
    FROM ai_server_performance 
    WHERE plugin_name = plugin_name_param 
    AND timestamp > NOW() - INTERVAL '1 hour' * hours_back;
END;
$ LANGUAGE plpgsql;

-- Create automatic cleanup job trigger function
CREATE OR REPLACE FUNCTION trigger_cache_cleanup()
RETURNS TRIGGER AS $
DECLARE
    plugin_rec RECORD;
BEGIN
    -- Run cleanup for all plugins when performance table gets too large
    IF (SELECT COUNT(*) FROM ai_server_performance) > 100000 THEN
        FOR plugin_rec IN SELECT DISTINCT plugin_name FROM ai_server_performance LOOP
            PERFORM cleanup_old_cache(plugin_rec.plugin_name, 30);
        END LOOP;
        
        -- Also cleanup old performance records
        DELETE FROM ai_server_performance 
        WHERE timestamp < NOW() - INTERVAL '90 days';
        
        -- Cleanup old logs
        DELETE FROM ai_server_logs 
        WHERE timestamp < NOW() - INTERVAL '60 days';
    END IF;
    
    RETURN NEW;
END;
$ LANGUAGE plpgsql;

-- Create trigger for automatic cleanup
CREATE TRIGGER trigger_automatic_cleanup
    AFTER INSERT ON ai_server_performance
    FOR EACH STATEMENT
    EXECUTE FUNCTION trigger_cache_cleanup();

-- Create function to update plugin configuration
CREATE OR REPLACE FUNCTION update_plugin_config(
    plugin_name_param TEXT,
    config_json JSONB,
    rate_limit INTEGER DEFAULT NULL,
    enabled_param BOOLEAN DEFAULT NULL
)
RETURNS BOOLEAN AS $
BEGIN
    UPDATE plugin_configurations 
    SET 
        configuration = COALESCE(config_json, configuration),
        rate_limit_per_minute = COALESCE(rate_limit, rate_limit_per_minute),
        enabled = COALESCE(enabled_param, enabled),
        updated_at = CURRENT_TIMESTAMP
    WHERE plugin_name = plugin_name_param;
    
    IF FOUND THEN
        INSERT INTO ai_server_logs (level, plugin_name, message, metadata)
        VALUES ('INFO', plugin_name_param, 'Plugin configuration updated', 
                json_build_object('new_config', config_json, 'rate_limit', rate_limit, 'enabled', enabled_param));
        RETURN TRUE;
    ELSE
        RETURN FALSE;
    END IF;
END;
$ LANGUAGE plpgsql;

-- Grant permissions on new tables and functions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO ai_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO ai_user;
GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO ai_user;
GRANT SELECT ON cache_statistics TO ai_user;

-- Create indexes for performance optimization
CREATE INDEX IF NOT EXISTS idx_plugin_config_name ON plugin_configurations(plugin_name);
CREATE INDEX IF NOT EXISTS idx_plugin_config_enabled ON plugin_configurations(enabled);

-- Analyze tables for optimal query planning
ANALYZE cache_chatgpt;
ANALYZE cache_flux;
ANALYZE cache_chatterbox;
ANALYZE ai_server_performance;
ANALYZE ai_server_logs;
ANALYZE plugin_configurations;

-- Success message
DO $
BEGIN
    RAISE NOTICE 'AI Server database initialized successfully!';
    RAISE NOTICE 'Plugin tables: cache_chatgpt, cache_flux, cache_chatterbox';
    RAISE NOTICE 'Monitoring tables: ai_server_performance, ai_server_logs';
    RAISE NOTICE 'Configuration table: plugin_configurations';
    RAISE NOTICE 'Utility functions: cleanup_old_cache, get_plugin_performance_metrics, update_plugin_config';
    RAISE NOTICE 'Views: cache_statistics';
    RAISE NOTICE 'Automatic cleanup triggers: enabled';
END $;