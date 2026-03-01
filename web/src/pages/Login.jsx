import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Card from '../components/common/Card';
import Button from '../components/common/Button';

/**
 * Login page stub — functional UI for future auth integration.
 * Currently stores a mock token in localStorage.
 */
export default function Login() {
    const navigate = useNavigate();
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);

    const handleSubmit = async (e) => {
        e.preventDefault();
        setError('');
        setLoading(true);

        try {
            // Stub auth — accept any non-empty credentials
            if (!username.trim() || !password.trim()) {
                throw new Error('请输入用户名和密码');
            }

            // In a real implementation, this would call an auth API
            const mockToken = btoa(`${username}:${Date.now()}`);
            localStorage.setItem('auth_token', mockToken);
            localStorage.setItem('auth_user', username);

            navigate('/dashboard');
        } catch (err) {
            setError(err.message || '登录失败');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen bg-gradient-to-br from-blue-900 via-gray-900 to-purple-900 flex items-center justify-center p-4">
            <div className="w-full max-w-md">
                {/* Logo */}
                <div className="text-center mb-8">
                    <h1 className="text-4xl font-bold text-white mb-2">🔍 ForensicsProject</h1>
                    <p className="text-gray-300">数字取证分析平台</p>
                </div>

                <Card>
                    <form onSubmit={handleSubmit} className="space-y-6 p-2">
                        <h2 className="text-2xl font-semibold text-gray-900 dark:text-white text-center">登录</h2>

                        {error && (
                            <div className="p-3 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-md">
                                <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
                            </div>
                        )}

                        <div>
                            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">用户名</label>
                            <input
                                type="text"
                                value={username}
                                onChange={(e) => setUsername(e.target.value)}
                                disabled={loading}
                                autoFocus
                                className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-700 dark:text-white"
                                placeholder="admin"
                            />
                        </div>

                        <div>
                            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">密码</label>
                            <input
                                type="password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                disabled={loading}
                                className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-700 dark:text-white"
                                placeholder="••••••••"
                            />
                        </div>

                        <Button type="submit" className="w-full py-3" disabled={loading}>
                            {loading ? '登录中...' : '登录'}
                        </Button>

                        <p className="text-xs text-center text-gray-400">
                            提示: 当前为演示模式，任意用户名密码均可登录
                        </p>
                    </form>
                </Card>
            </div>
        </div>
    );
}
